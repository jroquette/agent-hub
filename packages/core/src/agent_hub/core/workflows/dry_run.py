"""The dry run (docs/design/workflow-schema.md § Dry run and fixtures): the engine over stubs.

``dry_run`` hands the plan to the real ``run_workflow`` with a ``NodeRunner`` that answers each
attempt from the node's stubs, a clock that never waits and a recorder that keeps the steps in
memory: trigger rules, ``when:``, bindings, retries, loops and the ``output_format`` check
(through the ``OutputValidator`` port) are the engine's own. No child, no network, no event.

A single stub answers every attempt and iteration of its node; a list answers them in order. A
reached node with no stub, or whose list ran out, fails ``config`` and is listed as missing,
except under an ``all_done`` join: it gets a placeholder that fits its ``output_format``
(``skeleton_stub``), is listed as tolerated, and never sets the outcome. ``until_bash`` reads
the iteration's ``until_exit`` (default 0, done); a ``loop_group``'s ``until_bash`` has no stub
and reads 0, so a group that loops in a fixture ends through ``until_when``. ``approval`` and
``wait`` pause in the engine (AGH-230); until then a plan holding one is refused as a real run
refuses it.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Self

from pydantic import JsonValue, StrictInt, StrictStr, model_validator

from agent_hub.core.workflows.engine import EnginePorts, run_workflow
from agent_hub.core.workflows.failures import FailureKind, NodeFailedError, RetryRecord
from agent_hub.core.workflows.nodes import ExecutableNode, LoopNode, Node, WorkflowObject
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import (
    NodeCall,
    NodeReply,
    OutputValidator,
    RunEnd,
    StepEnd,
    StepStart,
)
from agent_hub.core.workflows.run_state import RunReport
from agent_hub.core.workflows.substitution import canonical_text

DRY_RUN_START: Final = datetime(2000, 1, 1, tzinfo=UTC)
PLACEHOLDER_TEXT: Final = "TODO"
# Bounds of one placeholder: items per array, and schema nodes visited in all.
MAX_PLACEHOLDER_ITEMS: Final = 3
PLACEHOLDER_BUDGET: Final = 1000
_ANSWERS: Final = frozenset({"output", "text", "fail"})
_SCALARS: Final[Mapping[str, JsonValue]] = {
    "boolean": False,
    "integer": 0,
    "number": 0,
    "null": None,
    "string": PLACEHOLDER_TEXT,
}


class Stub(WorkflowObject):
    """One attempt's answer: ``output`` (a value), ``text`` (the raw reply) or ``fail`` (a kind);
    ``until_exit`` is a loop iteration's ``until_bash`` exit."""

    output: JsonValue = None
    text: StrictStr | None = None
    fail: FailureKind | None = None
    until_exit: StrictInt | None = None

    @model_validator(mode="after")
    def _one_answer(self) -> Self:
        if len(_ANSWERS & self.model_fields_set) != 1:
            msg = "give exactly one of 'output', 'text' or 'fail'"
            raise ValueError(msg)
        return self


type Stubs = Stub | tuple[Stub, ...]


@dataclass(frozen=True)
class DryRunReport:
    """The engine's report and what the stubs saw. ``reached`` is in start order; ``failed`` in
    plan order; ``unused`` names stubbed nodes that never ran; ``steps`` every step end."""

    run: RunReport
    reached: tuple[str, ...]
    failed: tuple[str, ...]
    missing: tuple[str, ...]
    tolerated: tuple[str, ...]
    unused: tuple[str, ...]
    steps: tuple[StepEnd, ...]
    outcome: JsonValue


def dry_run(
    plan: WorkflowPlan,
    inputs: Mapping[str, JsonValue],
    stubs: Mapping[str, Stubs],
    *,
    outputs: OutputValidator,
) -> DryRunReport:
    """Run ``plan`` with ``inputs`` through the engine, each node answered from ``stubs``.

    Raises ``WorkflowEngineError`` when the engine refuses the run (inputs, an approval node).
    """
    runner, recorder = _StubRunner(stubs), _MemoryRecorder()
    ports = EnginePorts(runner, recorder, _StillClock(), outputs, lambda: 0.0)
    report = run_workflow(plan, inputs, ports)
    order = [node.id for node in plan.all_nodes()]
    returns = plan.document.returns
    return DryRunReport(
        run=report,
        reached=tuple(dict.fromkeys(start.node for start in recorder.starts)),
        failed=tuple(n for n in order if n in report.state.nodes and _failed(report, n)),
        missing=tuple(runner.missing),
        tolerated=tuple(runner.tolerated),
        unused=tuple(sorted(set(stubs) - set(runner.calls))),
        steps=tuple(recorder.ends),
        outcome=None if returns in runner.tolerated else report.outcome,
    )


def skeleton_stub(node: Node) -> dict[str, JsonValue]:
    """A stub that completes ``node``: a placeholder output that fits its ``output_format`` (a
    loop's ``until_field`` set), a loop's ``until`` text, else ``TODO``."""
    schema = getattr(node, "output_format", None)
    if schema is not None:
        value = placeholder(schema)
        if isinstance(node, LoopNode) and node.until_field and isinstance(value, dict):
            value[node.until_field] = True
        return {"output": value}
    if isinstance(node, LoopNode) and node.until is not None:
        return {"text": node.until}
    return {"text": PLACEHOLDER_TEXT}


def placeholder(schema: Mapping[str, JsonValue]) -> JsonValue:
    """A value meant to fit ``schema``: its ``const``, ``default`` or first ``enum``, else one per
    ``type``: an object's ``required`` properties, an array's ``minItems`` (at most
    ``MAX_PLACEHOLDER_ITEMS``), a number's ``minimum``, ``false``, ``0``, ``null`` or ``TODO``.

    Only those keywords are read: ``pattern``, ``minLength``, ``anyOf``/``oneOf``, ``$ref`` and
    the rest are not, so a schema leaning on them may not accept the value. At most
    ``PLACEHOLDER_BUDGET`` schema nodes are visited; past that an object is ``{}`` and an array
    ``[]``.
    """
    return _Placeholder().value(schema)


class _Placeholder:
    """One ``placeholder`` call: the schema nodes it may still visit."""

    def __init__(self) -> None:
        self.left = PLACEHOLDER_BUDGET

    def value(self, schema: Mapping[str, JsonValue]) -> JsonValue:
        self.left -= 1
        for key in ("const", "default"):
            if key in schema:
                return schema[key]
        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            return enum[0]
        kind = schema.get("type")
        if isinstance(kind, list):
            kind = kind[0] if kind else None
        if kind == "object":
            return {} if self.left < 0 else self._object(schema)
        if kind == "array":
            return [] if self.left < 0 else self._array(schema)
        return _scalar_placeholder(kind, schema.get("minimum"))

    def _object(self, schema: Mapping[str, JsonValue]) -> JsonValue:
        properties, required = schema.get("properties"), schema.get("required")
        known = properties if isinstance(properties, dict) else {}
        names = required if isinstance(required, list) else []
        return {
            name: self.value(_sub_schema(known.get(name)))
            for name in names
            if isinstance(name, str)
        }

    def _array(self, schema: Mapping[str, JsonValue]) -> JsonValue:
        count, items = schema.get("minItems"), _sub_schema(schema.get("items"))
        wanted = min(count, MAX_PLACEHOLDER_ITEMS) if type(count) is int else 0
        return [self.value(items) for _ in range(wanted)]


def _scalar_placeholder(kind: JsonValue, minimum: JsonValue) -> JsonValue:
    # A JSON boolean is a Python int: ``minimum: true`` is no number.
    if kind in {"integer", "number"} and type(minimum) in {int, float}:
        return minimum
    return _SCALARS.get(kind, PLACEHOLDER_TEXT) if isinstance(kind, str) else PLACEHOLDER_TEXT


def _sub_schema(value: JsonValue) -> Mapping[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _failed(report: RunReport, node: str) -> bool:
    return report.state.nodes[node].state == "failed"


class _StubRunner:
    """The ``NodeRunner`` of a dry run: each call takes the node's next stub."""

    def __init__(self, stubs: Mapping[str, Stubs]) -> None:
        self.stubs = stubs
        self.calls: dict[str, int] = {}
        self.current: dict[str, Stub] = {}
        self.missing: dict[str, None] = {}
        self.tolerated: dict[str, None] = {}

    def run(self, call: NodeCall) -> NodeReply:
        node = call.node
        stub = self._next(node.id)
        if stub is None:
            if node.trigger_rule != "all_done":
                self.missing[node.id] = None
                raise NodeFailedError("config", "the dry run has no stub left for this node")
            self.tolerated[node.id] = None
            stub = Stub.model_validate(skeleton_stub(node))
        self.current[node.id] = stub
        return _reply(node, stub)

    def until_exit(self, argv: Sequence[str], call: NodeCall) -> int:
        stub = self.current.get(call.node.id)
        return 0 if stub is None or stub.until_exit is None else stub.until_exit

    def _next(self, node_id: str) -> Stub | None:
        count = self.calls[node_id] = self.calls.get(node_id, 0) + 1
        given = self.stubs.get(node_id)
        if given is None or isinstance(given, Stub):
            return given
        return given[count - 1] if count <= len(given) else None


def _reply(node: ExecutableNode, stub: Stub) -> NodeReply:
    if stub.fail is not None:
        raise NodeFailedError(stub.fail, "a stubbed failure")
    if stub.text is not None:
        return NodeReply(stub.text)
    if node.output_format is not None:
        return NodeReply(json.dumps(stub.output, allow_nan=False))
    return NodeReply(canonical_text(stub.output))


class _StillClock:
    """A clock that starts at a fixed instant and only moves when a retry waits."""

    def __init__(self) -> None:
        self.current = DRY_RUN_START

    def now(self) -> datetime:
        return self.current

    def sleep(self, delay: timedelta) -> None:
        self.current += delay


@dataclass
class _MemoryRecorder:
    starts: list[StepStart] = field(default_factory=list)
    ends: list[StepEnd] = field(default_factory=list)

    def step_started(self, start: StepStart) -> None:
        self.starts.append(start)

    def step_ended(self, end: StepEnd) -> None:
        self.ends.append(end)

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None:
        pass

    def run_ended(self, end: RunEnd) -> None:
        pass
