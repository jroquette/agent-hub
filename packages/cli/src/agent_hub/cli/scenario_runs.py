"""A scenario run: ``hub scenario run``'s start, the engine's action runner, and the resume
(docs/design/scenarios.md § Plan and modes; ADR 0041).

A scenario run is a WorkflowRun of a ``kind: scenario`` document (``workflow_runs``): its folder
is ``.agent-runs/workflows/<run>/``, its events are labelled ``workflow: scenario:<name>``. The
caller plans the scenario first and starts nothing on a ``deny``, an undeclared environment or
any other plan problem. ``start`` then writes the snapshot: the document and its includes,
``policy_gates.json`` (each step the policy answered ``ask``, with its action, effect and
environment), and exactly the files each used action's ``content_hash`` pinned (its document,
script and pack helpers, as read: E-4) at their hub paths, ``actions/<pack>/…``. The start
record names the run's kind, label, environment and mode, and pins each action's hash
(``actions``) and the gated steps (``policy_gates``).

The run (and every resume, from ``hub workflow run --resume|approve|reject``) is planned from
the snapshot alone: the document with a ``<step>__ask`` approval before each gated step
(``policy_gates``), the actions read back from the snapshot and checked against their pins. So
an action edited during the run changes neither what runs nor its hash, and a resume takes up
the gates as recorded.

``ScenarioExecutors`` is the engine's ``NodeRunner``. Each ``action`` or ``expect`` call first
writes an ``action_start`` line (before any process: an expect's polls are counted from these
on resume, failed ones too, E-7). Then the call decides
the policy again (the effective config as it is now; origin ``author``): a ``deny``, or an
``ask`` the run has no gate for (the config tightened since the start), fails the step
``config`` before any process. It then resolves the call (each ``service`` input to its
endpoint in the run's environment), loads the credentials through the one env-file loader
(``action_command.call_credentials``) and runs the pinned action (``action_process``). Each call
is a ``policy.decision`` and, when it runs, ``action.start`` and ``action.end`` (approver: who
approved its gate), metadata only, and one ``action`` line in the record with its inputs. The
engine's trace (each ``expect`` poll, each ``capture:`` value) goes to the record
(``expect.poll``, ``context.capture``, with the output or value) and to the events (metadata
only). Each action runs in a process group of its own; an interrupted layer kills those groups
too (``stop_children``), and no action starts after it.

A call that may have run is never repeated silently. The ``action_start`` line of a write or
destroy is synced to disk before its process starts; on resume, the re-asks it owes and a
recorded reject of a policy gate are ``workflow_policy``'s rules, shared with process workflows.

The run's folder is removed when anything fails before its start record is written; the
snapshot keeps the includes the plan resolved, not a second read.

Only ``regression`` mode runs here: no agent starts, and a divergence (a failed action, an
``expect`` timeout, an output contract failure) fails the scenario run, printing ``step <id>:
<kind>: <detail>``; a policy ask or an ``approval`` still pauses it.
"""

import contextlib
import json
import os
import random
import shutil
import signal
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.action_command import call_credentials, deny_reason
from agent_hub.cli.action_process import ActionCall, run_action
from agent_hub.cli.collect import hub_project_name
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.run_log import now
from agent_hub.cli.workflow_command import own_hub_program
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.cli.workflow_policy import (
    GATES,
    Owed,
    gated_run_plan,
    gates_file,
    read_gates,
    rejected,
    resumed_prior,
)
from agent_hub.cli.workflow_policy import owed as _owed
from agent_hub.cli.workflow_runs import (
    ACTION_START,
    DOCUMENT,
    EXPECT_POLL,
    SNAPSHOT,
    EventSink,
    RecordedAnswers,
    RecordedRun,
    SystemClock,
    WorkflowRunError,
    append_record,
    ends_of,
    held_record,
    make_run,
    read_records,
    run_folder,
    run_lock,
    snapshot_includes,
    snapshot_run,
)
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import (
    Effect,
    PolicyDecision,
    decide,
    find_environment,
)
from agent_hub.core.scenarios.action_call import ActionCallError, ActionCallPlan, plan_action_call
from agent_hub.core.scenarios.action_catalog import ActionEntry, ActionRefError, resolve_action
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.scenarios.policy_gates import (
    PolicyAsk,
    ask_gate,
)
from agent_hub.core.scenarios.scenario_events import ActionFacts, ScenarioEvents
from agent_hub.core.scenarios.scenario_plan import ScenarioPlan
from agent_hub.core.workflows.document import WorkflowDocument, WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.engine import EnginePorts, run_workflow
from agent_hub.core.workflows.events import WorkflowEvents
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.includes import IncludeResolver
from agent_hub.core.workflows.nodes import ActionNode, ExpectNode
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.core.workflows.ports import (
    ContextCapture,
    ExpectPoll,
    NodeCall,
    NodeReply,
    RunEnd,
)
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions
from agent_hub.generator.scenario_discovery import discover_scenarios
from agent_hub.generator.workflow_discovery import DiscoveredWorkflow, pack_resolver
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import WorkflowMapping

KIND: Final = "scenario"
REGRESSION: Final = "regression"
INTERACTIVE: Final = "interactive"
MODES: Final = (INTERACTIVE, REGRESSION)
# Release gate (O-6): interactive mode lands with the investigation (T9).
INTERACTIVE_NOT_YET: Final = "interactive mode is not available yet: use --mode regression"
CONTEXT_CAPTURE: Final = "context.capture"
ACTION_CALL: Final = "action"
# A retry's jitter: spread, not secrecy.
_JITTER: Final = random.SystemRandom()


def scenario_label(name: str) -> str:
    """The ``workflow`` a scenario run's records and events carry: ``scenario:<name>``."""
    return f"{KIND}:{name}"


@dataclass(frozen=True, kw_only=True, slots=True)
class ScenarioStart:
    """What a scenario run starts from: the scenario as discovered and planned, its plan in the
    environment (no problem, no deny), the hub's actions and the inputs, defaults filled."""

    plan: WorkflowPlan
    found: DiscoveredWorkflow
    planned: ScenarioPlan
    actions: ActionDiscovery
    inputs: dict[str, JsonValue]
    mode: str
    # Each scenario the plan included, as resolved while planning: the snapshot keeps them.
    included: Mapping[str, WorkflowMapping]


def load_scenario(
    hub: Path, name: str
) -> tuple[WorkflowPlan, DiscoveredWorkflow, dict[str, WorkflowMapping]] | None:
    """The scenario ``name`` planned from one read of ``scenarios/``, with the includes that
    plan resolved (what a scenario run snapshots); ``None`` when there is no such scenario."""
    discovery = discover_scenarios(hub)
    found = next((item for item in discovery.workflows if item.name == name), None)
    if found is None:
        return None
    included: dict[str, WorkflowMapping] = {}
    resolver = pack_resolver(discovery, found.pack_root, used=included)
    try:
        plan = plan_workflow(parse_workflow(found.document), includes=resolver)
    except WorkflowLoadError as error:
        raise WorkflowRunError(f"cannot plan the scenario {name}: {error}") from None
    return plan, found, included


def start(hub: Path, run_id: str, begin: ScenarioStart) -> int:
    """Make the scenario run ``run_id``: its snapshot and start record, then run it; the exit
    code (0 done or paused, 1 otherwise). A snapshot that cannot be written leaves no run."""
    folder = run_folder(hub, run_id)
    make_run(folder)
    begun = False
    try:
        with run_lock(folder):
            header = _begin(folder, begin)
            begun = True
            inputs: dict[str, JsonValue] = {"event": "inputs", "inputs": begin.inputs}
            append_record(folder, inputs)
            return execute(hub, folder, [header, inputs], resumed=False)
    except BaseException:
        if not begun:
            # Nothing ran: a half-made run is not left to resume.
            shutil.rmtree(folder, ignore_errors=True)
        raise


def _begin(folder: Path, begin: ScenarioStart) -> dict[str, JsonValue]:
    """Write the snapshot, then the start record; the start record."""
    content_hash = _snapshot(folder, begin)
    planned, document = begin.planned, begin.plan.document
    header: dict[str, JsonValue] = {
        "event": "start",
        "run": folder.name,
        "workflow": scenario_label(document.name),
        "kind": KIND,
        "scenario": document.name,
        "pack": begin.found.pack,
        "revision": document.revision,
        "content_hash": content_hash,
        "environment": planned.environment,
        "mode": begin.mode,
        "actions": {row.action: row.content_hash for row in planned.rows},
        "policy_gates": list[JsonValue](sorted(_asks(planned))),
    }
    append_record(folder, header)
    return header


def resume(hub: Path, folder: Path, records: list[dict[str, JsonValue]]) -> int:
    """Continue a scenario run from its snapshot and records (the caller holds its lock and
    checked its snapshot's hash); its gates' answers are the recorded decisions."""
    append_record(folder, {"event": "resume"})
    return execute(hub, folder, records, resumed=True)


def execute(hub: Path, folder: Path, records: list[dict[str, JsonValue]], *, resumed: bool) -> int:
    """Run the scenario run in ``folder`` on the engine, as its snapshot pins it."""
    header, snapshot = records[0], folder / SNAPSHOT
    environment, pack = str(header.get("environment")), str(header.get("pack"))
    pinned = _pinned(snapshot, header)
    document, includes, recorded = _snapshot_parts(snapshot)
    owed = Owed()
    if resumed:
        base = _planned(document, includes, {})
        owed = _owed(
            folder,
            records,
            plan=base,
            effects=_effects(base, pinned, pack),
            environment=environment,
        )
    asks = recorded | owed.steps
    plan = _planned(document, includes, asks)
    effective = load_effective_config_or_exit(hub)
    view = effective_environments(effective.config, effective.local)
    hidden = CredentialNames.of(view)
    run_id, label = folder.name, str(header.get("workflow"))
    project = hub_project_name(hub) or hub.name
    revision = header.get("revision")
    events = WorkflowEvents(
        project=project,
        run_id=run_id,
        workflow=label,
        revision=revision if isinstance(revision, int) else 0,
        content_hash=str(header.get("content_hash")),
        end_index=len(ends_of(records)),
    )
    log = ScenarioLog(
        folder=folder,
        events=ScenarioEvents(project=project, run_id=run_id, workflow=label),
        sink=EventSink(),
    )
    inner = WorkflowExecutors(
        hub=hub,
        config=effective.config,
        run_id=run_id,
        pack_root=snapshot,
        environ=os.environ,
        hub_program=own_hub_program(),
        hidden=hidden,
    )
    runner = ScenarioExecutors(
        hub=hub,
        environment=environment,
        view=view,
        roots=(hub.name, *(repo.dir for repo in effective.config.repos)),
        pack=pack,
        pinned=pinned,
        asks=frozenset(asks),
        approvers=_approvers(records),
        log=log,
        inner=inner,
        environ=os.environ,
    )
    ports = EnginePorts(
        runner,
        RecordedRun(folder=folder, events=events, sink=EventSink()),
        SystemClock(),
        JsonSchemaOutputs(),
        _JITTER.random,
        None,
        max_parallel=inner.max_parallel,
        interrupt=runner.stop_children,
        gates=RecordedAnswers(records),
        trace=log,
    )
    if resumed and (cancelled := rejected(records)) is not None:
        # A recorded reject of a policy gate ends the run, whatever the plan holds now.
        ports.recorder.run_ended(RunEnd("cancelled", now(), reason=cancelled))
        typer.echo(f"run {run_id}: cancelled")
        return 1
    inputs = next((r["inputs"] for r in records if r.get("event") == "inputs"), {})
    report = run_workflow(
        plan,
        inputs if isinstance(inputs, dict) else {},
        ports,
        prior=resumed_prior(records, owed.reopen) if resumed else None,
    )
    append_record(folder, {"event": "sessions", "sessions": dict(report.state.sessions)})
    if report.status == "paused":
        append_record(folder, held_record(report.state))
        typer.echo(f"run {run_id}: paused at {report.reason}")
        return 0
    typer.echo(f"run {run_id}: {report.status}")
    if report.status == "failed" and report.reason is not None:
        typer.echo(_divergence(folder, report.reason))
    return 0 if report.status == "done" else 1


def _divergence(folder: Path, step: str) -> str:
    """``step <id>: <kind>: <detail>`` from the step's last failed end in the record."""
    ends = [
        record
        for record in read_records(folder)
        if record.get("event") == "step_end"
        and record.get("node") == step
        and record.get("status") == "failed"
    ]
    last = ends[-1] if ends else {}
    kind, detail = str(last.get("failure_kind") or "failed"), last.get("detail")
    shown = shown_text(detail) if isinstance(detail, str) and detail else ""
    return f"step {step}: {kind}" + (f": {shown}" if shown else "")


def _asks(planned: ScenarioPlan) -> dict[str, PolicyAsk]:
    """Each step the policy asks before, by its id as recorded."""
    return {
        row.step: PolicyAsk(action=row.action, effect=row.effect, environment=planned.environment)
        for row in planned.rows
        if row.decision == "ask"
    }


def _snapshot(folder: Path, begin: ScenarioStart) -> str:
    """Write the snapshot (document, includes, gates and the pinned action files); its hash."""
    used = {row.action for row in begin.planned.rows}
    pinned: dict[str, bytes] = {}
    for entry in begin.actions.actions:
        if entry.ref in used:
            pinned.update(begin.actions.files[entry.document_path])
    pinned[GATES] = gates_file(_asks(begin.planned))
    _, content_hash = snapshot_run(
        folder,
        document=dict(begin.found.document),
        plan=begin.plan,
        pack_root=begin.found.pack_root,
        includes=dict(begin.included),
        pinned=pinned,
    )
    return content_hash


def _effects(plan: WorkflowPlan, pinned: PinnedActions, pack: str) -> dict[str, tuple[str, Effect]]:
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


def _snapshot_parts(
    snapshot: Path,
) -> tuple[WorkflowDocument, IncludeResolver, dict[str, PolicyAsk]]:
    """The snapshot's document, its includes and the gates ``policy_gates.json`` names."""
    try:
        document = parse_workflow(json.loads((snapshot / DOCUMENT).read_bytes()))
        asks = read_gates(json.loads((snapshot / GATES).read_bytes()))
    except (OSError, ValueError, WorkflowLoadError) as error:
        raise WorkflowRunError(f"cannot load the scenario run's snapshot: {error}") from None
    return document, snapshot_includes(snapshot), asks


def _planned(
    document: WorkflowDocument, includes: IncludeResolver, asks: Mapping[str, PolicyAsk]
) -> WorkflowPlan:
    """The run's plan, a gate before each step of ``asks``."""
    return gated_run_plan(document, includes, asks)


@dataclass(frozen=True, kw_only=True, slots=True)
class PinnedActions:
    """The actions a scenario run pinned, read back from its snapshot, and their files."""

    entries: tuple[ActionEntry, ...]
    files: Mapping[str, tuple[tuple[str, bytes], ...]]


def _pinned(snapshot: Path, header: Mapping[str, JsonValue]) -> PinnedActions:
    """The snapshot's actions, each checked against the hash the start record pinned."""
    found = discover_actions(snapshot)
    if found.problems:
        raise WorkflowRunError(
            f"the scenario run's pinned actions do not load: {found.problems[0]}"
        )
    pins = header.get("actions")
    entries: list[ActionEntry] = []
    for ref, content_hash in (pins if isinstance(pins, dict) else {}).items():
        entry = next((item for item in found.actions if item.ref == ref), None)
        if entry is None or entry.content_hash != content_hash:
            raise WorkflowRunError(f"the scenario run's snapshot no longer holds {ref} as pinned")
        entries.append(entry)
    files = {entry.document_path: found.files[entry.document_path] for entry in entries}
    return PinnedActions(entries=tuple(entries), files=files)


def _approvers(records: list[dict[str, JsonValue]]) -> dict[str, str]:
    """Who decided each gate, by its node as recorded (the last decision)."""
    return {
        str(record.get("node")): str(record.get("approver"))
        for record in records
        if record.get("event") == "decision" and isinstance(record.get("approver"), str)
    }


@dataclass(kw_only=True)
class ScenarioLog:
    """A scenario run's own lines and events: the engine's ``RunTrace`` (polls, captures) and
    each action call. Outputs, values and inputs go to the record; events keep metadata."""

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

    def begun(self, call: NodeCall, entry: ActionEntry | None) -> None:
        """The call's ``action_start`` line, before anything else of it: one per call (an
        expect's polls are counted from them) and the mark of a call that may have run."""
        line: dict[str, JsonValue] = {"event": ACTION_START, "node": call.node.id}
        line |= {"attempt": call.attempt, "poll": call.poll}
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
class ScenarioExecutors:
    """The engine's ``NodeRunner`` for a scenario run: its ``action`` and ``expect`` calls, each
    decided again, then run from the pinned files; ``until_bash`` as any workflow's."""

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
    log: ScenarioLog
    inner: WorkflowExecutors
    environ: Mapping[str, str]
    # The process groups of the actions running now: ``stop_children`` kills them.
    running: set[int] = field(default_factory=set)
    # Set by ``stop_children``: no action starts after it, and one starting as it lands is killed.
    stop: threading.Event = field(default_factory=threading.Event)

    def stop_children(self) -> None:
        """Kill every running action's group and the other children (an interrupted layer)."""
        self.stop.set()
        for group in list(self.running):
            _kill(group)
        self.inner.stop_children()

    def run(self, call: NodeCall) -> NodeReply:
        node = call.node
        if not isinstance(node, ActionNode | ExpectNode):
            raise NodeFailedError("config", f"{node.type} nodes do not run in a scenario run")
        entry = self._entry(node)
        self.log.begun(call, entry)
        if entry is None:
            raise NodeFailedError("config", f"the scenario run pinned no action {node.action}")
        declared = find_environment(self.view, self.environment)
        decision = decide(declared, entry.document.effect, "author")
        facts = ActionFacts(
            step=node.id,
            attempt=call.attempt,
            action=entry.ref,
            content_hash=entry.content_hash,
            environment=self.environment,
            services=(),
            effect=entry.document.effect,
            origin="author",
            decision=decision.decision,
            approver=self.approvers.get(ask_gate(node.id)) if node.id in self.asks else None,
        )
        self.log.decided(facts, decision, poll=call.poll)
        line = CallLine(
            facts=facts,
            reason_kind=decision.reason_kind,
            poll=call.poll,
            inputs=call.inputs,
            started=False,
        )
        planned = self._checked(entry, decision, line)
        return self._run(entry, planned, line)

    def until_exit(self, argv: Sequence[str], call: NodeCall) -> int:
        return self.inner.until_exit(argv, call)

    def _entry(self, node: ActionNode | ExpectNode) -> ActionEntry | None:
        try:
            return resolve_action(self.pinned.entries, node.action, pack=self.pack)
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
                " this scenario run has no gate for it: start a new scenario run"
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
                raise NodeFailedError("cancelled", "the scenario run was interrupted")
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
