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
- ``agent_action``: an investigation read (``hub action run --run``);
- ``workaround_start`` and ``workaround_end``: ``workaround_id``, ``number``, ``option``, ``steps``,
  ``approver``, ``status``.

The gate is answered by a ``decision`` line and closed by a ``step_end`` line on it. The view
also keeps each ``expect.poll`` (its node, attempt, poll and whether the condition held; never
its output), each ``context.capture`` (its name and value) and each ``decision`` on any gate.
"""

import dataclasses
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.policy_gates import INVESTIGATION

PROPOSAL: Final = "proposal"
AGENT_ACTION: Final = "agent_action"
WORKAROUND_START: Final = "workaround_start"
WORKAROUND_END: Final = "workaround_end"
EXPECT_POLL: Final = "expect.poll"
CONTEXT_CAPTURE: Final = "context.capture"
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
    about, its status and when."""

    event: str
    node: str | None
    attempt: int | None
    status: str | None
    at: str | None


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
        """The investigation whose gate is still open, while the run has no end."""
        last = self.investigations[-1] if self.investigations else None
        if self.status is not None or last is None or last.closed:
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

    def add(self, record: Record) -> None:
        event = _text(record.get("event"))
        if event is None:
            return
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


def _item(event: str, record: Record) -> TimelineItem:
    node = next(
        (value for key in ("node", "step", "gate") if isinstance(value := record.get(key), str)),
        None,
    )
    attempt = record.get("attempt", record.get("number"))
    return TimelineItem(
        event=event,
        node=node,
        attempt=attempt if isinstance(attempt, int) else None,
        status=_text(record.get("status")),
        at=_text(record.get("ts")),
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
