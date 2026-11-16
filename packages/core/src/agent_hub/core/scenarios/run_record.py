"""A scenario run read from its record (P-16): ``records.jsonl``'s lines folded into a view.

The CLI (``hub scenario propose``, ``hub action run --run``, the answer checks) and the API read
the same lines: ``record_lines`` parses the bytes (a last line without its newline, a torn
write, is dropped) and ``fold_records`` builds the ``ScenarioRunView``: its timeline, each
investigation with its answer and its latest proposal (a later proposal of the same
investigation replaces the earlier), the findings kept (each investigation's latest), the
workarounds and the end. Lines it does not know are left out of the view, never refused.

The lines a scenario run's investigation writes (``cli/scenario_investigation.py``, and
``cli/action_command.py`` for ``agent_action``):

- ``investigation``: ``step``, ``gate``, ``number`` (from 1, the gate's attempt), ``step_attempt``
  and ``failure_kind`` of the divergence; then a ``gate`` line on ``gate``;
- ``proposal``: ``gate``, ``number``, ``proposal`` (from 1 in the run), ``findings`` (each
  ``finding_id``, ``title``, ``text``, ``evidence``) and ``options`` (each ``option_id``,
  ``summary``, ``steps`` and their ``plan``);
- ``agent_action``: an investigation read (``hub action run --run``), its timeline line naming
  its action and effect;
- ``workaround_start`` and ``workaround_end``: ``workaround_id``, ``number``, ``option``, ``steps``,
  ``approver``, ``status``.

The gate is answered by a ``decision`` line and closed by a ``step_end`` line on it. The view
also keeps each ``expect.poll`` (its node, attempt, poll and whether the condition held; never
its output), each ``context.capture`` (its name and value), each ``decision`` on any gate and
each ``action`` line: an action call's policy facts (action, effect, origin, decision, content
hash, status), never its inputs or output.

A debugging run (ADR 0049; docs/design/scenarios.md § Debugging) adds three lines, which
``ScenarioRunView.debug`` folds:

- ``debug.breakpoints``: ``addresses``, the run's breakpoints as set (the latest line holds them);
- ``debug.pause``: ``node``, ``block``, ``reason`` and ``number`` (from 1 in the run), with what
  the resume goes on with (``debug_pause_line``): the stopped ``pass``, the open ``gates`` and
  the policy ``asks`` that pass's plan held beyond the snapshot's (a resume's re-asks), so the
  resume plans the same layers;
- ``debug.command``: ``command`` (``step`` or ``continue``), ``approver``, and the ``node`` and
  ``number`` of the pause it resumes.

The run control also writes ``debug.breakpoints_unreadable`` (``reason``: why the breakpoints
file counted as none), which the view leaves out.

A pause is the run's while no ``resume``, ``start`` or ``end`` line follows it: then the run is
paused by the debugger, not by a gate an earlier pass left open (``open_investigation`` is
``None``). ``debug_resume`` reads the pass back, so a run rebuilt from its record resumes as the
in-memory state would. ``fold_values`` gives what a paused run shows to inspect: the run's
effective inputs and each finished node's rendered inputs, status and last output (an expect's
polls and last poll output); they stay out of the ``ScenarioRunView``, which is metadata.
"""

import dataclasses
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, get_args

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import Effect
from agent_hub.core.scenarios.policy_gates import INVESTIGATION, PolicyAsk
from agent_hub.core.workflows.failures import FailureKind
from agent_hub.core.workflows.gates import OpenGate
from agent_hub.core.workflows.ports import SkipCause
from agent_hub.core.workflows.run_control import DebugPause, DebugReason
from agent_hub.core.workflows.run_state import NodeEnd, PausedPass, RunState
from agent_hub.core.workflows.substitution import NodeResult, NodeState

PROPOSAL: Final = "proposal"
AGENT_ACTION: Final = "agent_action"
WORKAROUND_START: Final = "workaround_start"
WORKAROUND_END: Final = "workaround_end"
EXPECT_POLL: Final = "expect.poll"
CONTEXT_CAPTURE: Final = "context.capture"
ACTION_CALL: Final = "action"
ACTION_START: Final = "action_start"
DEBUG_PAUSE: Final = "debug.pause"
DEBUG_COMMAND: Final = "debug.command"
DEBUG_BREAKPOINTS: Final = "debug.breakpoints"
DEBUG_BREAKPOINTS_UNREADABLE: Final = "debug.breakpoints_unreadable"
# The lines after which a debug pause is no longer the run's: the pass it stopped went on.
_PASS_LINES: Final = frozenset({"start", "resume", "end"})
_NODE_STATES: Final = frozenset(get_args(NodeState.__value__))
_SKIP_CAUSES: Final = frozenset(get_args(SkipCause.__value__))
_FAILURE_KINDS: Final = frozenset(get_args(FailureKind.__value__))
_EFFECTS: Final = frozenset(get_args(Effect))
_DEBUG_REASONS: Final = frozenset(get_args(DebugReason.__value__))
TIMELINE_EVENTS: Final = frozenset(
    {
        "start",
        "resume",
        "step_start",
        "step_end",
        "gate",
        "decision",
        INVESTIGATION,
        PROPOSAL,
        AGENT_ACTION,
        WORKAROUND_START,
        WORKAROUND_END,
        "end",
    }
)

type Record = Mapping[str, JsonValue]


class RunRecordError(AgentHubError):
    """A record line, before its last, that is not one JSON object."""


class RecordTooLargeError(RunRecordError):
    """A run record larger than its reader reads (the API's bound)."""


@dataclass(frozen=True, kw_only=True, slots=True)
class TimelineItem:
    """One line of the timeline: its event, the node (or step, or gate) and attempt it is
    about, its status and when; an investigation read's (``agent_action``) action and effect."""

    event: str
    node: str | None
    attempt: int | None
    status: str | None
    at: str | None
    action: str | None = None
    effect: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class FindingView:
    finding_id: str
    step: str
    title: str
    text: str
    evidence: str


@dataclass(frozen=True, kw_only=True, slots=True)
class OptionView:
    """An option as proposed: its steps (``action``, ``with``) and their plan when proposed."""

    option_id: str
    summary: str
    steps: tuple[Mapping[str, JsonValue], ...]
    plan: tuple[Mapping[str, JsonValue], ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class ProposalView:
    proposal: int
    number: int
    findings: tuple[FindingView, ...]
    options: tuple[OptionView, ...]

    def option(self, option_id: str) -> OptionView | None:
        return next((item for item in self.options if item.option_id == option_id), None)


@dataclass(frozen=True, kw_only=True, slots=True)
class InvestigationView:
    """One investigation: the diverged step, its gate, the answer once given and whether the
    gate closed; its latest proposal."""

    number: int
    step: str
    gate: str
    failure_kind: str | None
    choice: str | None = None
    text: str | None = None
    approver: str | None = None
    closed: bool = False
    proposal: ProposalView | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class WorkaroundView:
    workaround_id: str
    number: int
    option: str
    steps: int
    approver: str | None
    status: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class PollView:
    """One poll of an ``expect`` step: whether its condition held (its output is left out)."""

    node: str
    attempt: int | None
    poll: int | None
    held: bool | None
    at: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class CaptureView:
    """A value a step captured into the run's context (``$CTX.<name>``)."""

    node: str
    attempt: int | None
    name: str
    value: JsonValue


@dataclass(frozen=True, kw_only=True, slots=True)
class DecisionView:
    """A recorded answer to one of the run's gates: who, where and with what."""

    node: str
    attempt: int | None
    choice: str | None
    text: str | None
    approver: str | None
    where: str | None
    at: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class ActionCallView:
    """One action call's policy facts, from its ``action`` line: the step (node, attempt and
    an expect's poll), the action and its pinned content hash, its effect, who planned it
    (``origin``), the policy's decision and who answered an ask; its inputs and output are
    left out."""

    node: str
    attempt: int | None
    poll: int | None
    action: str | None
    effect: str | None
    origin: str | None
    decision: str | None
    reason_kind: str | None
    content_hash: str | None
    approver: str | None
    status: str | None
    failure_kind: str | None
    at: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class DebugPauseView:
    """The debug pause the run is in: the node it stopped before, that node's block, why
    (``breakpoint`` or ``step``), its number in the run and when."""

    node: str
    block: str
    reason: str
    number: int
    at: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class DebugCommandView:
    """A Step or Continue: who sent it, the number of the pause it resumed and when."""

    command: str
    approver: str | None
    number: int | None
    at: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class DebugView:
    """A run's debugging: its pause while it is in one, its breakpoints (block addresses, as
    last set) and every command; ``stepping`` while the last command was a Step."""

    pause: DebugPauseView | None = None
    breakpoints: tuple[str, ...] = ()
    commands: tuple[DebugCommandView, ...] = ()

    @property
    def stepping(self) -> bool:
        return bool(self.commands) and self.commands[-1].command == "step"


@dataclass(frozen=True, kw_only=True, slots=True)
class ScenarioRunView:
    """A scenario run as its record holds it; ``status`` is its last end's, ``None`` while it
    has none."""

    run: str | None
    scenario: str | None
    environment: str | None
    mode: str | None
    status: str | None
    timeline: tuple[TimelineItem, ...]
    investigations: tuple[InvestigationView, ...]
    workarounds: tuple[WorkaroundView, ...]
    pack: str | None = None
    polls: tuple[PollView, ...] = ()
    captures: tuple[CaptureView, ...] = ()
    decisions: tuple[DecisionView, ...] = ()
    actions: tuple[ActionCallView, ...] = ()
    debug: DebugView = field(default_factory=DebugView)

    @property
    def findings(self) -> tuple[FindingView, ...]:
        """Every investigation's findings, from its latest proposal: kept whatever the end."""
        return tuple(
            finding
            for item in self.investigations
            if item.proposal is not None
            for finding in item.proposal.findings
        )

    @property
    def open_investigation(self) -> InvestigationView | None:
        """The investigation whose gate is still open, while the run has no end and is not in a
        debug pause (a gate an earlier pass left open is not why the run is paused)."""
        last = self.investigations[-1] if self.investigations else None
        if self.status is not None or self.debug.pause is not None:
            return None
        if last is None or last.closed:
            return None
        return last


def record_lines(data: bytes) -> list[dict[str, JsonValue]]:
    """The record's lines, parsed; a last line without its newline (a torn write) is left out.
    Raises ``RunRecordError`` on another line that is not one JSON object."""
    lines: list[dict[str, JsonValue]] = []
    for line in data.split(b"\n")[:-1]:
        try:
            value = json.loads(line)
        except ValueError:
            value = None
        if not isinstance(value, dict):
            msg = "a record line is not one JSON object"
            raise RunRecordError(msg)
        lines.append(value)
    return lines


def fold_records(records: Iterable[Record]) -> ScenarioRunView:
    """The scenario run ``records`` describe."""
    fold = _Fold()
    for record in records:
        fold.add(record)
    header = fold.header
    return ScenarioRunView(
        run=_text(header.get("run")),
        scenario=_text(header.get("scenario")),
        environment=_text(header.get("environment")),
        mode=_text(header.get("mode")),
        status=fold.status,
        timeline=tuple(fold.timeline),
        investigations=tuple(fold.investigations.values()),
        workarounds=tuple(fold.workarounds.values()),
        pack=_text(header.get("pack")),
        polls=tuple(fold.polls),
        captures=tuple(fold.captures),
        decisions=tuple(fold.decisions),
        actions=tuple(fold.actions),
        debug=DebugView(
            pause=fold.pause,
            breakpoints=fold.breakpoints,
            commands=tuple(fold.commands),
        ),
    )


class _Fold:
    def __init__(self) -> None:
        self.header: Record = {}
        self.status: str | None = None
        self.timeline: list[TimelineItem] = []
        self.investigations: dict[int, InvestigationView] = {}
        # Each investigation's gate, so its decision and end are found by node and attempt.
        self.gates: dict[tuple[str, int], int] = {}
        self.workarounds: dict[str, WorkaroundView] = {}
        self.polls: list[PollView] = []
        self.captures: list[CaptureView] = []
        self.decisions: list[DecisionView] = []
        self.actions: list[ActionCallView] = []
        self.pause: DebugPauseView | None = None
        self.breakpoints: tuple[str, ...] = ()
        self.commands: list[DebugCommandView] = []

    def add(self, record: Record) -> None:
        event = _text(record.get("event"))
        if event is None:
            return
        if event in _PASS_LINES:
            self.pause = None
        if event == "start" and not self.header:
            self.header = record
        if event in TIMELINE_EVENTS:
            self.timeline.append(_item(event, record))
        handlers = {
            "end": self._end,
            INVESTIGATION: self._investigation,
            PROPOSAL: self._proposal,
            "decision": self._decision,
            "step_end": self._gate_closed,
            WORKAROUND_START: self._workaround,
            WORKAROUND_END: self._workaround_end,
            EXPECT_POLL: self._poll,
            CONTEXT_CAPTURE: self._capture,
            ACTION_CALL: self._action,
            DEBUG_PAUSE: self._debug_pause,
            DEBUG_COMMAND: self._debug_command,
            DEBUG_BREAKPOINTS: self._breakpoints,
        }
        if (handler := handlers.get(event)) is not None:
            handler(record)

    def _end(self, record: Record) -> None:
        self.status = _text(record.get("status"))

    def _investigation(self, record: Record) -> None:
        number, step, gate = record.get("number"), record.get("step"), record.get("gate")
        if not (isinstance(number, int) and isinstance(step, str) and isinstance(gate, str)):
            return
        self.investigations[number] = InvestigationView(
            number=number,
            step=step,
            gate=gate,
            failure_kind=_text(record.get("failure_kind")),
        )
        self.gates[(gate, number)] = number

    def _proposal(self, record: Record) -> None:
        number, proposal = record.get("number"), record.get("proposal")
        found = self.investigations.get(number) if isinstance(number, int) else None
        if found is None or not isinstance(proposal, int):
            return
        view = ProposalView(
            proposal=proposal,
            number=found.number,
            findings=tuple(_finding(item, found.step) for item in _list(record.get("findings"))),
            options=tuple(_option(item) for item in _list(record.get("options"))),
        )
        self.investigations[found.number] = dataclasses.replace(found, proposal=view)

    def _poll(self, record: Record) -> None:
        if (node := _text(record.get("node"))) is not None:
            held = record.get("held")
            self.polls.append(
                PollView(
                    node=node,
                    attempt=_int(record.get("attempt")),
                    poll=_int(record.get("poll")),
                    held=held if isinstance(held, bool) else None,
                    at=_text(record.get("ts")),
                )
            )

    def _capture(self, record: Record) -> None:
        node, name = _text(record.get("node")), _text(record.get("name"))
        if node is not None and name is not None:
            self.captures.append(
                CaptureView(
                    node=node,
                    attempt=_int(record.get("attempt")),
                    name=name,
                    value=record.get("value"),
                )
            )

    def _action(self, record: Record) -> None:
        if (node := _text(record.get("node"))) is not None:
            self.actions.append(
                ActionCallView(
                    node=node,
                    attempt=_int(record.get("attempt")),
                    poll=_int(record.get("poll")),
                    action=_text(record.get("action")),
                    effect=_text(record.get("effect")),
                    origin=_text(record.get("origin")),
                    decision=_text(record.get("decision")),
                    reason_kind=_text(record.get("reason_kind")),
                    content_hash=_text(record.get("content_hash")),
                    approver=_text(record.get("approver")),
                    status=_text(record.get("status")),
                    failure_kind=_text(record.get("failure_kind")),
                    at=_text(record.get("ts")),
                )
            )

    def _decision(self, record: Record) -> None:
        if (node := _text(record.get("node"))) is not None:
            self.decisions.append(
                DecisionView(
                    node=node,
                    attempt=_int(record.get("attempt")),
                    choice=_text(record.get("choice")),
                    text=_text(record.get("text")),
                    approver=_text(record.get("approver")),
                    where=_text(record.get("where")),
                    at=_text(record.get("ts")),
                )
            )
        if (found := self._gate_of(record)) is not None:
            self.investigations[found.number] = dataclasses.replace(
                found,
                choice=_text(record.get("choice")),
                text=_text(record.get("text")),
                approver=_text(record.get("approver")),
            )

    def _gate_closed(self, record: Record) -> None:
        if (found := self._gate_of(record)) is not None:
            self.investigations[found.number] = dataclasses.replace(found, closed=True)

    def _gate_of(self, record: Record) -> InvestigationView | None:
        node, attempt = record.get("node"), record.get("attempt")
        if not isinstance(node, str) or not isinstance(attempt, int):
            return None
        number = self.gates.get((node, attempt))
        return None if number is None else self.investigations[number]

    def _debug_pause(self, record: Record) -> None:
        node, block = _text(record.get("node")), _text(record.get("block"))
        reason, number = _text(record.get("reason")), _int(record.get("number"))
        if node is None or block is None or reason is None or number is None:
            return
        at = _text(record.get("ts"))
        self.pause = DebugPauseView(node=node, block=block, reason=reason, number=number, at=at)

    def _debug_command(self, record: Record) -> None:
        if (command := _text(record.get("command"))) is not None:
            self.commands.append(
                DebugCommandView(
                    command=command,
                    approver=_text(record.get("approver")),
                    number=_int(record.get("number")),
                    at=_text(record.get("ts")),
                )
            )

    def _breakpoints(self, record: Record) -> None:
        addresses = _list(record.get("addresses"))
        self.breakpoints = tuple(item for item in addresses if isinstance(item, str))

    def _workaround(self, record: Record) -> None:
        workaround, number = _text(record.get("workaround_id")), record.get("number")
        steps = record.get("steps")
        if workaround is None or not isinstance(number, int):
            return
        self.workarounds[workaround] = WorkaroundView(
            workaround_id=workaround,
            number=number,
            option=_text(record.get("option")) or "",
            steps=steps if isinstance(steps, int) else 0,
            approver=_text(record.get("approver")),
            status=None,
        )

    def _workaround_end(self, record: Record) -> None:
        found = self.workarounds.get(_text(record.get("workaround_id")) or "")
        if found is not None:
            status = _text(record.get("status"))
            self.workarounds[found.workaround_id] = dataclasses.replace(found, status=status)


@dataclass(frozen=True, kw_only=True, slots=True)
class NodeValues:
    """A finished node's values, as its record lines hold them: its last end's status and
    output, the inputs its last action call rendered (``None`` for a node that calls none) and,
    for an expect, its polls in the run and the last poll's output."""

    node: str
    attempt: int | None
    status: str | None
    inputs: JsonValue
    output: JsonValue
    polls: int = 0
    last_poll: JsonValue = None


@dataclass(frozen=True, kw_only=True, slots=True)
class RunValues:
    """What a paused run shows to inspect: its effective inputs (the ``inputs`` line, environment
    values included) and each finished node's values, in the order they first ended."""

    inputs: Mapping[str, JsonValue]
    nodes: tuple[NodeValues, ...]


def fold_values(records: Iterable[Record]) -> RunValues:
    """The values ``records`` hold. A reuse's end (``prior_success``) keeps the end it reused;
    an expect's polls are its ``action_start`` lines with a ``poll``, as the engine counts them."""
    inputs: Mapping[str, JsonValue] = {}
    ends: dict[str, Record] = {}
    calls: dict[str, JsonValue] = {}
    polls: dict[str, int] = {}
    last_polls: dict[str, JsonValue] = {}
    for record in records:
        event, node = _text(record.get("event")), _text(record.get("node"))
        if event == "inputs" and not inputs and isinstance(given := record.get("inputs"), dict):
            inputs = given
        if node is None:
            continue
        if event == "step_end" and record.get("skip_cause") != "prior_success":
            ends[node] = record
        elif event == ACTION_CALL and "inputs" in record:
            calls[node] = record.get("inputs")
        elif event == ACTION_START and (_int(record.get("poll")) or 0) > 0:
            polls[node] = polls.get(node, 0) + 1
        elif event == EXPECT_POLL:
            last_polls[node] = record.get("output")
    return RunValues(
        inputs=inputs,
        nodes=tuple(
            NodeValues(
                node=node,
                attempt=_int(end.get("attempt")),
                status=_text(end.get("status")),
                inputs=calls.get(node),
                output=end.get("output"),
                polls=polls.get(node, 0),
                last_poll=last_polls.get(node),
            )
            for node, end in ends.items()
        ),
    )


@dataclass(frozen=True)
class DebugResume:
    """What a run's debug pause leaves for its resume, read back from its ``debug.pause`` line:
    the pause, the pass it stopped, the gates open then (the pass's own and an earlier pass's it
    had not reached) and the policy asks that pass's plan held beyond the snapshot's, by step
    (re-asks owed then): the resume plans with them, so its plan has the layers the pass ran on.
    The rest of the run's state comes from its other lines."""

    pause: DebugPause
    paused_pass: PausedPass
    gates: Mapping[str, OpenGate]
    asks: Mapping[str, PolicyAsk] = field(default_factory=dict)

    def applied_to(self, state: RunState) -> RunState:
        """``state`` (rebuilt from the run's other lines) with this pause, its pass and its
        gates, as the engine left them."""
        return dataclasses.replace(
            state, gates=dict(self.gates), pause=self.pause, paused_pass=self.paused_pass
        )


def debug_pause_line(
    state: RunState, *, number: int, asks: Mapping[str, PolicyAsk] | None = None
) -> dict[str, JsonValue]:
    """The ``debug.pause`` line of ``state``, a report's state paused by run control: the pause,
    its ``number`` in the run, the stopped pass, the open gates and ``asks``, the policy asks the
    pass's plan held beyond the snapshot's. Its groups go in the ``held`` line, as a gate
    pause's do."""
    pause, paused = state.pause, state.paused_pass
    if pause is None or paused is None:
        msg = "the state is not paused by run control"
        raise ValueError(msg)
    passing: dict[str, JsonValue] = {
        "layer": paused.layer,
        "ends": {node: _end_line(end) for node, end in paused.ends.items()},
        "before": {node: _result_line(result) for node, result in paused.before.items()},
        "changed": list[JsonValue](sorted(paused.changed)),
        "stale": list[JsonValue](sorted(paused.stale)),
        "gate": paused.gate,
    }
    gates: dict[str, JsonValue] = {
        node: {"attempt": gate.attempt, "due": None if gate.due is None else gate.due.isoformat()}
        for node, gate in state.gates.items()
    }
    planned: dict[str, JsonValue] = {
        step: {"action": ask.action, "effect": ask.effect, "environment": ask.environment}
        | {"again": ask.again}
        for step, ask in (asks or {}).items()
    }
    line: dict[str, JsonValue] = {"event": DEBUG_PAUSE, "node": pause.node}
    line |= {"block": pause.block, "reason": pause.reason, "number": number}
    return line | {"pass": passing, "gates": gates, "asks": planned}


def debug_resume(records: Iterable[Record]) -> DebugResume | None:
    """The debug pause the run is in, read back for its resume, or ``None`` when it is in none
    (read the record before the resume writes its ``resume`` line). Raises ``RunRecordError``
    when that pause's line cannot be read: resumed from a guess, the pass would go on wrong."""
    current: Record | None = None
    for record in records:
        event = record.get("event")
        if event in _PASS_LINES:
            current = None
        elif event == DEBUG_PAUSE:
            current = record
    if current is None:
        return None
    try:
        return _resumed(current)
    except TypeError, ValueError, KeyError:
        msg = "the run's debug pause line cannot be read"
        raise RunRecordError(msg) from None


def _resumed(line: Record) -> DebugResume:
    node, block, reason = line["node"], line["block"], line["reason"]
    passing, gates = line["pass"], line["gates"]
    if not (isinstance(node, str) and isinstance(block, str) and reason in _DEBUG_REASONS):
        raise ValueError(node)
    if not isinstance(passing, dict) or not isinstance(gates, dict):
        raise TypeError(passing)
    layer, gate = passing["layer"], passing["gate"]
    if _int(layer) is None or not (gate is None or isinstance(gate, str)):
        raise ValueError(layer)
    paused = PausedPass(
        layer=int(layer),  # type: ignore[arg-type]
        ends={key: _end_of(value) for key, value in _object(passing["ends"]).items()},
        before={key: _result_of(value) for key, value in _object(passing["before"]).items()},
        changed=frozenset(_names(passing["changed"])),
        stale=frozenset(_names(passing["stale"])),
        gate=gate,
    )
    opened = {key: _gate_of(value) for key, value in gates.items()}
    asks = {key: _ask_of(value) for key, value in _object(line["asks"]).items()}
    return DebugResume(DebugPause(node, block, reason), paused, opened, asks)  # type: ignore[arg-type]


def _result_line(result: NodeResult) -> JsonValue:
    return {"state": result.state, "output": result.output}


def _end_line(end: NodeEnd) -> JsonValue:
    line: dict[str, JsonValue] = {"state": end.result.state, "output": end.result.output}
    optional = {"skip_cause": end.cause, "origin": end.origin, "failure_kind": end.failure_kind}
    return line | {key: value for key, value in optional.items() if value is not None}


def _result_of(value: JsonValue) -> NodeResult:
    given = _object(value)
    state = given["state"]
    if state not in _NODE_STATES:
        raise ValueError(state)
    return NodeResult(state, given.get("output"))  # type: ignore[arg-type]


def _end_of(value: JsonValue) -> NodeEnd:
    given = _object(value)
    cause, origin, kind = given.get("skip_cause"), given.get("origin"), given.get("failure_kind")
    if cause is not None and cause not in _SKIP_CAUSES:
        raise ValueError(cause)
    if kind is not None and kind not in _FAILURE_KINDS:
        raise ValueError(kind)
    if origin is not None and not isinstance(origin, str):
        raise TypeError(origin)
    return NodeEnd(_result_of(given), cause, origin, kind)  # type: ignore[arg-type]


def _gate_of(value: JsonValue) -> OpenGate:
    given = _object(value)
    attempt, due = _int(given["attempt"]), given.get("due")
    if attempt is None or not (due is None or isinstance(due, str)):
        raise ValueError(attempt)
    return OpenGate(attempt, None if due is None else datetime.fromisoformat(due))


def _ask_of(value: JsonValue) -> PolicyAsk:
    given = _object(value)
    action, effect = given["action"], given["effect"]
    environment, again = given["environment"], given["again"]
    if effect not in _EFFECTS:
        raise ValueError(effect)
    if not (isinstance(action, str) and isinstance(environment, str) and isinstance(again, bool)):
        raise TypeError(action)
    return PolicyAsk(action=action, effect=effect, environment=environment, again=again)  # type: ignore[arg-type]


def _object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise TypeError(value)
    return value


def _names(value: JsonValue) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(value)
    return [item for item in value if isinstance(item, str)]


def _item(event: str, record: Record) -> TimelineItem:
    node = next(
        (value for key in ("node", "step", "gate") if isinstance(value := record.get(key), str)),
        None,
    )
    attempt = record.get("attempt", record.get("number"))
    read = event == AGENT_ACTION
    return TimelineItem(
        event=event,
        node=node,
        attempt=attempt if isinstance(attempt, int) else None,
        status=_text(record.get("status")),
        at=_text(record.get("ts")),
        action=_text(record.get("action")) if read else None,
        effect=_text(record.get("effect")) if read else None,
    )


def _finding(value: JsonValue, step: str) -> FindingView:
    given = value if isinstance(value, dict) else {}
    return FindingView(
        finding_id=_text(given.get("finding_id")) or "",
        step=step,
        title=_text(given.get("title")) or "",
        text=_text(given.get("text")) or "",
        evidence=_text(given.get("evidence")) or "",
    )


def _option(value: JsonValue) -> OptionView:
    given = value if isinstance(value, dict) else {}
    return OptionView(
        option_id=_text(given.get("option_id")) or "",
        summary=_text(given.get("summary")) or "",
        steps=tuple(item for item in _list(given.get("steps")) if isinstance(item, dict)),
        plan=tuple(item for item in _list(given.get("plan")) if isinstance(item, dict)),
    )


def _list(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def _text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
