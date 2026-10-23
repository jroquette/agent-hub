"""The action calls of a run in an environment: a scenario run's, and a process workflow's
(docs/design/scenarios.md; ADR 0041, E-1, E-4, E-9).

A run that holds action nodes pins each used action at its start: the start record's
``actions`` maps ``<pack>/<name>`` to its ``content_hash``, and the snapshot holds exactly the
files that hash covers (``pinned_files``), at their hub paths ``actions/<pack>/…``. Every resume
reads them back from the snapshot and checks them against the pins (``pinned_actions``), so an
action edited during the run changes neither what runs nor its hash.

``ActionExecutors`` runs each ``action`` or ``expect`` call. It first writes an ``action_start``
line (before any process; a write's is synced to disk, so a resume asks again: E-9, and an
expect's polls are counted from these lines, E-7). Then it decides the policy again, with the
effective config as loaded when this process started or resumed the run (origin ``author``): a
``deny``, or an ``ask`` the run has no gate for, fails the step ``config`` before any process. It
then resolves the call (each ``service`` input to its endpoint in the run's environment), loads
the credentials through the one env-file loader (``action_command.call_credentials``) and runs
the pinned action (``action_process``), whose output is redacted of every injected value. Each
call is a ``policy.decision`` and, when it runs, ``action.start`` and ``action.end`` (approver:
who approved its gate), metadata only, and one ``action`` line in the record with its inputs.
Each action runs in a process group of its own; ``stop_children`` (the engine's interrupt) kills
those groups and the wrapped executors' children, and no action starts after it.

``ActionLog`` is also the engine's ``RunTrace`` (each ``expect`` poll and ``capture:`` value to the
record and, metadata only, the events) and sends a process workflow's node decisions.
"""

import contextlib
import json
import os
import signal
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agent_hub.cli.action_command import call_credentials
from agent_hub.cli.action_process import ActionCall, run_action
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.cli.workflow_runs import (
    ACTION_START,
    EXPECT_POLL,
    EventSink,
    SystemClock,
    WorkflowRunError,
    append_record,
)
from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import (
    Effect,
    Origin,
    PolicyDecision,
    decide,
    deny_reason,
    find_environment,
)
from agent_hub.core.scenarios.action_call import (
    ActionCallError,
    ActionCallPlan,
    plan_action_call,
    with_run_values,
)
from agent_hub.core.scenarios.action_catalog import ActionEntry, ActionRefError, resolve_action
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.scenarios.policy_gates import NodeDecision, ask_gate
from agent_hub.core.scenarios.scenario_events import ActionFacts, ScenarioEvents
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.nodes import ActionNode, ExpectNode
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import ContextCapture, ExpectPoll, NodeCall, NodeReply
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions

CONTEXT_CAPTURE: Final = "context.capture"
ACTION_CALL: Final = "action"


def pinned_files(actions: ActionDiscovery, refs: frozenset[str]) -> dict[str, bytes]:
    """Exactly the files each action of ``refs`` pinned (its document, script and pack
    helpers, as read: E-4), by hub path: what a run's snapshot holds."""
    pinned: dict[str, bytes] = {}
    for entry in actions.actions:
        if entry.ref in refs:
            pinned.update(actions.files[entry.document_path])
    return pinned


def action_effects(
    plan: WorkflowPlan, pinned: PinnedActions, pack: str
) -> dict[str, tuple[str, Effect]]:
    """Each action step's pinned action and effect, by its id as recorded."""
    found: dict[str, tuple[str, Effect]] = {}
    for node in plan.all_nodes():
        if isinstance(node, ActionNode | ExpectNode):
            try:
                entry = resolve_action(pinned.entries, node.action, pack=pack)
            except ActionRefError:
                continue
            found[node.id] = (entry.ref, entry.document.effect)
    return found


@dataclass(frozen=True, kw_only=True, slots=True)
class PinnedActions:
    """The actions a run pinned, read back from its snapshot, and their files."""

    entries: tuple[ActionEntry, ...]
    files: Mapping[str, tuple[tuple[str, bytes], ...]]


def pinned_actions(
    snapshot: Path, header: Mapping[str, JsonValue], *, noun: str = "scenario run"
) -> PinnedActions:
    """The snapshot's actions, each checked against the hash the start record pinned."""
    found = discover_actions(snapshot)
    if found.problems:
        raise WorkflowRunError(f"the {noun}'s pinned actions do not load: {found.problems[0]}")
    pins = header.get("actions")
    entries: list[ActionEntry] = []
    for ref, content_hash in (pins if isinstance(pins, dict) else {}).items():
        entry = next((item for item in found.actions if item.ref == ref), None)
        if entry is None or entry.content_hash != content_hash:
            raise WorkflowRunError(f"the {noun}'s snapshot no longer holds {ref} as pinned")
        entries.append(entry)
    files = {entry.document_path: found.files[entry.document_path] for entry in entries}
    return PinnedActions(entries=tuple(entries), files=files)


def approvers(records: list[dict[str, JsonValue]]) -> dict[str, str]:
    """Who decided each gate, by its node as recorded (the last decision)."""
    return {
        str(record.get("node")): str(record.get("approver"))
        for record in records
        if record.get("event") == "decision" and isinstance(record.get("approver"), str)
    }


@dataclass(kw_only=True)
class ActionLog:
    """A run's action lines and events: the engine's ``RunTrace`` (polls, captures), each
    action call and each node decision. Outputs, values and inputs go to the record; events
    keep metadata."""

    folder: Path
    events: ScenarioEvents
    sink: EventSink
    lock: threading.Lock = field(default_factory=threading.Lock)

    def expect_polled(self, poll: ExpectPoll) -> None:
        line: dict[str, JsonValue] = {"event": EXPECT_POLL, "node": poll.node}
        line |= {"attempt": poll.attempt, "poll": poll.poll, "held": poll.held}
        with self.lock:
            append_record(self.folder, line | {"output": poll.output})
            self.events.expect_polled(poll)
            self.sink.flush(self.events)

    def context_captured(self, capture: ContextCapture) -> None:
        line: dict[str, JsonValue] = {"event": CONTEXT_CAPTURE, "node": capture.node}
        line |= {"attempt": capture.attempt, "name": capture.name, "value": capture.value}
        with self.lock:
            append_record(self.folder, line)
            self.events.context_captured(capture)
            self.sink.flush(self.events)

    def begun(self, step: str, *, attempt: int, poll: int, entry: ActionEntry | None) -> None:
        """The call's ``action_start`` line, before anything else of it: one per call (an
        expect's polls are counted from them) and the mark of a call that may have run."""
        line: dict[str, JsonValue] = {"event": ACTION_START, "node": step}
        line |= {"attempt": attempt, "poll": poll}
        if entry is not None:
            line |= {"action": entry.ref, "effect": entry.document.effect}
        # A write's start must outlive the hub: a resume reads it to ask again.
        durable = entry is None or entry.document.effect != "read"
        with self.lock:
            append_record(self.folder, line, durable=durable)

    def decided(self, facts: ActionFacts, decision: PolicyDecision, *, poll: int) -> None:
        with self.lock:
            now = SystemClock().now()
            self.events.policy_decided(facts, reason_kind=decision.reason_kind, at=now, poll=poll)
            self.sink.flush(self.events)

    def node_decided(self, decision: NodeDecision, *, attempt: int, item: str = "") -> None:
        """A shell, script or ``until_bash`` node's decision as a ``policy.decision`` event."""
        with self.lock:
            self.events.node_decided(decision, attempt=attempt, at=SystemClock().now(), item=item)
            self.sink.flush(self.events)

    def started(self, facts: ActionFacts, *, poll: int) -> None:
        with self.lock:
            self.events.action_started(facts, at=SystemClock().now(), poll=poll)
            self.sink.flush(self.events)

    def ended(self, call: CallLine, *, status: str, failure_kind: str | None) -> None:
        """The call's ``action`` line (its inputs too), and ``action.end`` when it started."""
        facts = call.facts
        with self.lock:
            line: dict[str, JsonValue] = {"event": ACTION_CALL, "node": facts.step}
            line |= {"attempt": facts.attempt, "poll": call.poll, **facts.called()}
            line |= {"reason_kind": call.reason_kind, "inputs": dict(call.inputs)}
            append_record(self.folder, line | {"status": status, "failure_kind": failure_kind})
            if call.started:
                at = SystemClock().now()
                self.events.action_ended(
                    facts, status=status, failure_kind=failure_kind, at=at, poll=call.poll
                )
                self.sink.flush(self.events)


@dataclass(frozen=True, kw_only=True, slots=True)
class CallLine:
    """One action call as its ``action`` line records it."""

    facts: ActionFacts
    reason_kind: str
    poll: int
    inputs: Mapping[str, JsonValue]
    started: bool


@dataclass(frozen=True, kw_only=True)
class ActionExecutors:
    """The ``action`` and ``expect`` calls of a run in an environment (a scenario run's
    ``NodeRunner``, and a process workflow's through ``workflow_policy.NodePolicyRunner``):
    each decided again, then run from the pinned files; ``until_bash`` as any workflow's."""

    hub: Path
    environment: str
    view: EffectiveEnvironments
    # The folders an env file may be in, relative to the workspace: the hub's and each repo's.
    roots: tuple[str, ...]
    pack: str
    pinned: PinnedActions
    # The steps (as recorded) the run has a policy gate before.
    asks: frozenset[str]
    # Who decided each gate, by its node as recorded.
    approvers: Mapping[str, str]
    log: ActionLog
    inner: WorkflowExecutors
    environ: Mapping[str, str]
    # The process groups of the actions running now: ``stop_children`` kills them.
    running: set[int] = field(default_factory=set)
    # Set by ``stop_children``: no action starts after it, and one starting as it lands is killed.
    stop: threading.Event = field(default_factory=threading.Event)
    # What its messages call the run.
    noun: str = "scenario run"
    # Who proposed the calls: the run's document, or an agent (a picked workaround's steps,
    # whose asks the pick answered: they are in ``asks``).
    origin: Origin = "author"

    def stop_children(self) -> None:
        """Kill every running action's group and the other children (an interrupted layer)."""
        self.stop.set()
        for group in list(self.running):
            _kill(group)
        self.inner.stop_children()

    def run(self, call: NodeCall) -> NodeReply:
        node = call.node
        if not isinstance(node, ActionNode | ExpectNode):
            raise NodeFailedError("config", f"{node.type} nodes do not run as actions")
        entry = self._entry(node.action)
        # The run's values (its scenario inputs) for the action's inputs the step leaves out.
        inputs = (
            call.inputs
            if entry is None
            else with_run_values(entry.document.inputs, call.inputs, call.context.inputs)
        )
        return self.run_call(
            node.id, action=node.action, attempt=call.attempt, poll=call.poll, inputs=inputs
        )

    def run_call(
        self,
        step: str,
        *,
        action: str,
        attempt: int,
        inputs: Mapping[str, JsonValue],
        poll: int = 0,
    ) -> NodeReply:
        """One call of ``action`` as step ``step`` (its id as recorded), decided for this
        runner's ``origin``: an engine node's, or a picked workaround's step."""
        entry = self._entry(action)
        self.log.begun(step, attempt=attempt, poll=poll, entry=entry)
        if entry is None:
            raise NodeFailedError("config", f"the {self.noun} pinned no action {action}")
        declared = find_environment(self.view, self.environment)
        decision = decide(declared, entry.document.effect, self.origin)
        facts = ActionFacts(
            step=step,
            attempt=attempt,
            action=entry.ref,
            content_hash=entry.content_hash,
            environment=self.environment,
            services=(),
            effect=entry.document.effect,
            origin=self.origin,
            decision=decision.decision,
            approver=self.approvers.get(ask_gate(step)) if step in self.asks else None,
        )
        self.log.decided(facts, decision, poll=poll)
        line = CallLine(
            facts=facts,
            reason_kind=decision.reason_kind,
            poll=poll,
            inputs=inputs,
            started=False,
        )
        planned = self._checked(entry, decision, line)
        return self._run(entry, planned, line)

    def until_exit(self, argv: Sequence[str], call: NodeCall) -> int:
        return self.inner.until_exit(argv, call)

    def _entry(self, action: str) -> ActionEntry | None:
        try:
            return resolve_action(self.pinned.entries, action, pack=self.pack)
        except ActionRefError:
            return None

    def _started(self, group: int) -> None:
        self.running.add(group)
        if self.stop.is_set():
            # The stop came between the check before the start and this start.
            _kill(group)

    def _checked(
        self, entry: ActionEntry, decision: PolicyDecision, line: CallLine
    ) -> ActionCallPlan:
        """The call's plan once the policy lets it run; else the step fails ``config``."""
        refused = self._refusal(line.facts.step, entry, decision)
        if refused is None:
            try:
                return plan_action_call(
                    entry.document, line.inputs, environment=self.environment, view=self.view
                )
            except ActionCallError as error:
                refused = f"{entry.ref}: {error}"
        self.log.ended(line, status="failed", failure_kind="config")
        raise NodeFailedError("config", refused)

    def _refusal(self, step: str, entry: ActionEntry, decision: PolicyDecision) -> str | None:
        """Why the policy, decided now, refuses the call; ``None`` when it may run: an
        ``allow``, or an ``ask`` whose gate the run has (the engine ran it only once approved)."""
        effect = entry.document.effect
        if decision.decision == "deny":
            declared = find_environment(self.view, self.environment)
            reason = deny_reason(
                decision,
                effect=effect,
                environment=self.environment,
                access=declared.access if declared is not None else None,
            )
            return f"the policy denies {entry.ref} ({effect}) in {self.environment}: {reason}"
        if decision.decision == "ask" and step not in self.asks:
            return (
                f"the policy now asks before {entry.ref} ({effect}) in {self.environment} and"
                f" this {self.noun} has no gate for it: start a new {self.noun}"
            )
        return None

    def _run(self, entry: ActionEntry, planned: ActionCallPlan, line: CallLine) -> NodeReply:
        facts = line.facts.model_copy(update={"services": planned.services})
        line = CallLine(
            facts=facts,
            reason_kind=line.reason_kind,
            poll=line.poll,
            inputs=planned.inputs,
            started=True,
        )
        self.log.started(facts, poll=line.poll)
        declared = find_environment(self.view, self.environment)
        groups: list[int] = []

        def started(group: int) -> None:
            groups.append(group)
            self._started(group)

        try:
            injected = (
                {}
                if declared is None
                else call_credentials(
                    self.hub,
                    declared,
                    endpoints=planned.endpoints,
                    roots=self.roots,
                    environ=self.environ,
                )
            )
            if self.stop.is_set():
                raise NodeFailedError("cancelled", f"the {self.noun} was interrupted")
            output = run_action(
                ActionCall(
                    entry=entry,
                    files=self.pinned.files[entry.document_path],
                    inputs=planned.inputs,
                    endpoint=planned.endpoint,
                ),
                environ=self.environ,
                hidden=CredentialNames.of(self.view),
                credentials=injected,
                on_start=started,
            )
        except NodeFailedError as error:
            self.log.ended(line, status="failed", failure_kind=error.kind)
            raise
        finally:
            self.running.difference_update(groups)
        self.log.ended(line, status="ok", failure_kind=None)
        return NodeReply(json.dumps(output))


def _kill(group: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGKILL)
