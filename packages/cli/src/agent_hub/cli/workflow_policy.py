"""Policy gates on a run, for scenario runs and process workflows alike (P-4, P-18, E-9;
docs/design/scenarios.md § Policy).

A run that has policy gates keeps its authored document in its snapshot, and beside it
``policy_gates.json``: each step the policy asked before at the start, with what runs there, its
effect and the environment (``gates_file``, ``read_gates``). ``parse_workflow`` refuses an id
ending ``__ask``, so the gated plan is never snapshotted: ``gated_run_plan`` rebuilds it from those
two files at the start and on every resume.

A step that may have run is never repeated silently. Before a write or destroy starts, the
runner writes a durable start line (``action_start`` for an action call, ``node_start`` for a
process workflow's shell or script node). On resume (``owed``), a step outside a loop_group whose
write started and that never ended after, and a loop_group with a write of its body started after
its last clean point (its end, or a pause recorded with it held), owe a re-ask: it is recorded
once as a durable ``reask_owed`` line and read back from the record (never from attempt numbers).
An owed step asks through a ``<step>__ask`` gate whose message says it may have run, until the
step ends; an owed group asks before every write or destroy of its body, each iteration, until
the group ends. A read step simply runs again. A recorded reject of any policy gate
(``rejected``) ends the run ``cancelled`` on resume, whatever the plan holds now.

A process workflow run in an environment runs its nodes through ``NodePolicyRunner``: each
``shell`` and ``script`` node is decided again just before it starts (the effective config as it
is then, origin ``author``), and a ``deny``, or an ``ask`` the run has no gate for (the config
tightened since the start), fails it ``config`` before any process. It starts no process of its
own: the workflow executors it wraps do, and its ``stop_children`` stops theirs.
"""

import dataclasses
import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, get_args

from agent_hub.cli.action_command import deny_reason
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.cli.workflow_runs import (
    ACTION_START,
    WorkflowRunError,
    append_record,
    prior_state,
)
from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import Effect, decide, find_environment
from agent_hub.core.scenarios.policy_gates import (
    ASK_SUFFIX,
    PolicyAsk,
    PolicyGateError,
    ask_gate,
    gated_plan,
    node_effect,
)
from agent_hub.core.workflows.document import WorkflowDocument, WorkflowLoadError
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.includes import IncludeResolver
from agent_hub.core.workflows.nodes import LoopGroupNode
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import NodeCall, NodeReply
from agent_hub.core.workflows.run_state import RunState

GATES: Final = "policy_gates.json"
# A re-ask the run owes after a call that may have run (``owed``).
REASK_OWED: Final = "reask_owed"
# A process workflow's write or destroy node, written before its process starts.
NODE_START: Final = "node_start"
_STARTS: Final = frozenset({ACTION_START, NODE_START})
_EFFECTS: Final[tuple[Effect, ...]] = get_args(Effect)

type Record = dict[str, JsonValue]


def gates_file(asks: Mapping[str, PolicyAsk]) -> bytes:
    """``policy_gates.json``'s bytes: each gated step's action, effect and environment."""
    gates = {
        step: {"action": ask.action, "effect": ask.effect, "environment": ask.environment}
        for step, ask in asks.items()
    }
    return json.dumps(gates, sort_keys=True).encode()


def read_gates(value: object) -> dict[str, PolicyAsk]:
    """The gates ``policy_gates.json`` (parsed) names; ``ValueError`` when it is malformed."""
    if not isinstance(value, dict):
        msg = f"{GATES} is not an object"
        raise ValueError(msg)
    asks: dict[str, PolicyAsk] = {}
    for step, ask in value.items():
        given = ask if isinstance(ask, dict) else {}
        action, effect, where = given.get("action"), given.get("effect"), given.get("environment")
        known = next((item for item in _EFFECTS if item == effect), None)
        if not (isinstance(action, str) and known is not None and isinstance(where, str)):
            msg = f"{GATES}: the gate of {step} is malformed"
            raise ValueError(msg)
        asks[step] = PolicyAsk(action=action, effect=known, environment=where)
    return asks


def snapshot_gates(snapshot: Path) -> dict[str, PolicyAsk]:
    """The gates a run's snapshot holds; ``WorkflowRunError`` when they cannot be read."""
    try:
        return read_gates(json.loads((snapshot / GATES).read_bytes()))
    except (OSError, ValueError) as error:
        raise WorkflowRunError(f"cannot load the run's snapshot: {error}") from None


def gated_run_plan(
    document: WorkflowDocument, includes: IncludeResolver | None, asks: Mapping[str, PolicyAsk]
) -> WorkflowPlan:
    """The run's plan, a gate before each step of ``asks``; ``WorkflowRunError`` when it does
    not plan (two unordered gates, a gate naming no step)."""
    try:
        return gated_plan(document, includes=includes, asks=asks)
    except (WorkflowLoadError, PolicyGateError) as error:
        raise WorkflowRunError(f"cannot plan the run's policy gates: {error}") from None


def node_effects(plan: WorkflowPlan, environment: str) -> dict[str, tuple[str, Effect]]:
    """Each shell and script node's type and effect in ``environment``, by its id as
    recorded (what ``owed`` asks again for a process workflow)."""
    found: dict[str, tuple[str, Effect]] = {}
    for node in plan.all_nodes():
        if (effect := node_effect(node, environment=environment)) is not None:
            found[node.id] = (node.type, effect)
    return found


@dataclass(frozen=True, kw_only=True, slots=True)
class Owed:
    """The re-asks a resume owes: each step asked again (by its id as recorded), and the gates
    whose earlier answer no longer counts."""

    steps: dict[str, PolicyAsk] = field(default_factory=dict)
    reopen: frozenset[str] = frozenset()


def owed(
    folder: Path,
    records: list[Record],
    *,
    plan: WorkflowPlan,
    effects: Mapping[str, tuple[str, Effect]],
    environment: str,
) -> Owed:
    """The re-asks this resume owes, each first recorded as a durable ``reask_owed`` line.

    A step outside a loop_group is owed when a write or destroy of it started and the step
    never ended after; it stays owed until the step ends, and its earlier gate answer counts
    only once a gate was opened after the owed line. A loop_group is owed when a write or
    destroy of its body started after its last clean point (its end, or a pause recorded with
    it held): the group may run that body again, so every write or destroy of its body asks
    first until the group ends. Nothing is derived from attempt numbers."""
    bodies = {
        group.id: tuple(body.id for body in group.nodes)
        for group in plan.document.nodes
        if isinstance(group, LoopGroupNode)
    }
    owner = {body: group for group, ids in bodies.items() for body in ids}
    marks = _Marks.of(records)
    for node in [*bodies, *(step for step in effects if step not in owner)]:
        if _newly_owed(node, marks, bodies.get(node)):
            line: Record = {"event": REASK_OWED, "node": node}
            append_record(folder, line, durable=True)
            marks.owed[node] = len(records) + len(marks.added)
            marks.added.append(node)
    steps: dict[str, PolicyAsk] = {}
    reopen: set[str] = set()
    for node, at in marks.owed.items():
        if at <= marks.ended.get(node, -1):
            continue
        for step in bodies.get(node, (node,)):
            if step in effects and effects[step][1] != "read":
                action, effect = effects[step]
                steps[step] = PolicyAsk(
                    action=action, effect=effect, environment=environment, again=True
                )
        if node not in bodies and marks.gates.get(ask_gate(node), -1) < at:
            reopen.add(ask_gate(node))
    return Owed(steps=steps, reopen=frozenset(reopen))


@dataclass(kw_only=True)
class _Marks:
    """Where things last happened in a run's record, by line index and node as recorded."""

    ended: dict[str, int] = field(default_factory=dict)
    held: dict[str, int] = field(default_factory=dict)
    owed: dict[str, int] = field(default_factory=dict)
    gates: dict[str, int] = field(default_factory=dict)
    # The last write or destroy started of each node.
    writes: dict[str, int] = field(default_factory=dict)
    added: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, records: list[Record]) -> _Marks:
        marks = cls()
        for index, record in enumerate(records):
            node, event = record.get("node"), record.get("event")
            if event == "held" and isinstance(groups := record.get("groups"), dict):
                marks.held |= dict.fromkeys(groups, index)
            if not isinstance(node, str):
                continue
            if event in _STARTS and record.get("effect") in ("write", "destroy"):
                marks.writes[node] = index
            found = {"step_end": marks.ended, REASK_OWED: marks.owed, "gate": marks.gates}
            if (where := found.get(str(event))) is not None:
                where[node] = index
        return marks


def _newly_owed(node: str, marks: _Marks, body: tuple[str, ...] | None) -> bool:
    """Whether ``node`` owes a re-ask its record does not hold yet."""
    if body is None:
        started = marks.writes.get(node, -1)
        return started > marks.ended.get(node, -1) and marks.owed.get(node, -1) < started
    clean = max(marks.ended.get(node, -1), marks.held.get(node, -1))
    started = max((marks.writes.get(step, -1) for step in body), default=-1)
    return started > clean and marks.owed.get(node, -1) <= clean


def rejected(records: list[Record]) -> str | None:
    """A policy gate a recorded decision rejected, if any."""
    return next(
        (
            str(record.get("node"))
            for record in records
            if record.get("event") == "decision"
            and record.get("choice") == "reject"
            and str(record.get("node")).endswith(ASK_SUFFIX)
        ),
        None,
    )


def resumed_prior(records: list[Record], reopen: frozenset[str]) -> RunState:
    """The run's state for a resume, without the earlier answer of each gate in ``reopen``."""
    prior = prior_state(records)
    if not reopen:
        return prior
    nodes = {node: result for node, result in prior.nodes.items() if node not in reopen}
    return dataclasses.replace(prior, nodes=nodes)


@dataclass(frozen=True, kw_only=True)
class NodePolicyRunner:
    """The engine's ``NodeRunner`` for a process workflow run in an environment: each shell and
    script node decided again before it starts, then run by ``inner``."""

    inner: WorkflowExecutors
    folder: Path
    environment: str
    view: EffectiveEnvironments
    # The steps (as recorded) the run has a policy gate before.
    asks: frozenset[str]
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def max_parallel(self) -> int:
        return self.inner.max_parallel

    def stop_children(self) -> None:
        """Stop the children the wrapped executors run (an interrupted layer)."""
        self.inner.stop_children()

    def run(self, call: NodeCall) -> NodeReply:
        node = call.node
        effect = node_effect(node, environment=self.environment)
        if effect is not None:
            if (refused := self._refusal(node.id, effect)) is not None:
                raise NodeFailedError("config", refused)
            if effect != "read":
                # A write's start must outlive the hub: a resume reads it to ask again.
                line: Record = {"event": NODE_START, "node": node.id, "attempt": call.attempt}
                with self.lock:
                    append_record(self.folder, line | {"effect": effect}, durable=True)
        return self.inner.run(call)

    def until_exit(self, argv: Sequence[str], call: NodeCall) -> int:
        return self.inner.until_exit(argv, call)

    def _refusal(self, step: str, effect: Effect) -> str | None:
        """Why the policy, decided now, refuses the node; ``None`` when it may run: an
        ``allow``, or an ``ask`` whose gate the run has (the engine ran it only once approved)."""
        declared = find_environment(self.view, self.environment)
        decision = decide(declared, effect, "author")
        if decision.decision == "deny":
            reason = deny_reason(
                decision,
                effect=effect,
                environment=self.environment,
                access=declared.access if declared is not None else None,
            )
            return f"the policy denies step {step} ({effect}) in {self.environment}: {reason}"
        if decision.decision == "ask" and step not in self.asks:
            return (
                f"the policy now asks before step {step} ({effect}) in {self.environment} and"
                " this run has no gate for it: start a new run"
            )
        return None
