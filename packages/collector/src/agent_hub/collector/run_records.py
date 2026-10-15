"""``hub run`` records (``.agent-runs/*.jsonl``) to executor events (D8, D9, E7).

A run's stages are its record ``state``s. The first record in a new state ends the stage before
it (``step.end`` ``ok``, unless a ``failed`` record already ended it) and starts the new one
(``step.start``, ``attempt`` = how many times the run entered that stage). ``picked`` carries the
caps, ``gate_ok`` is a passed ``gate.result``, ``failed`` ends its stage ``failed`` with the first
line of the reason and its ``failure_kind`` when it has one (AGH-224), and ``reported`` is the
``run.end``: ``done`` only when the run did not fail and its report was made. Every event has
session ``run:<run id>`` and workflow ``issue-to-pr``.

The ``run.end`` also carries the run's ``outcome`` (AGH-140), apart from its status: the
``reported`` record's own, or for a record written before it, ``delivered`` when it names a PR
and ``failed`` otherwise. ``not_delivered`` (no commit, or the session stopped) is no failure:
its stage still ends ``ok`` and the ``run.end`` keeps its reason.

``source_id`` (E7): ``<run>:<state>:<event>:<ts>:<type>``, and for step events ``:<stage>`` after
it, since one record can end one stage, start another and fail it. Records are mapped in file
order, one run's state kept per run id, so the live ``hub run`` and a later
``hub collect --runs`` of the same records yield the same events.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from agent_hub.collector.errors import CollectorError
from agent_hub.collector.hook_fields import text
from agent_hub.collector.tool_metadata import COMMAND_LIMIT, first_line, short_text
from agent_hub.core.events.event import MAX_ID_CHARS, Event, EventSource, EventType
from agent_hub.core.events.payload_keys import CAPS_KEYS
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.run_record import NOT_DELIVERED, RunOutcome, Stage
from agent_hub.core.workflows.failures import FAILURE_KINDS

RUN_WORKFLOW: Final = "issue-to-pr"
# A run's events are the session ``run:<run>``, which must fit the id cap.
RUN_SESSION_PREFIX: Final = "run:"
MAX_RUN_CHARS: Final = MAX_ID_CHARS - len(RUN_SESSION_PREFIX)
STAGE_KEYS: Final[Mapping[str, str]] = {
    Stage.PICKED: "pick",
    Stage.WORKTREE: "worktree",
    Stage.IMPLEMENTING: "implement",
    Stage.VERIFYING: "verify",
    Stage.PR_OPEN: "pr",
}
# The caps a picked record carries, in a fixed order; the core table says which may be stored.
CAPS: Final = tuple(sorted(CAPS_KEYS))
GATE_KIND: Final = "check"

type Payload = dict[str, JsonValue]
type Record = Mapping[str, JsonValue]


class RunRecordError(CollectorError):
    """A run record that cannot be mapped; the message names the field."""


@dataclass(frozen=True, kw_only=True, slots=True)
class _Record:
    """The fields of one valid record."""

    raw: Record
    ts: str
    moment: datetime
    run: str
    state: str
    event: str

    @property
    def base(self) -> Payload:
        payload: Payload = {"run": self.run}
        for key in ("issue", "repo"):
            value = text(self.raw, key)
            if value is not None:
                payload[key] = value
        payload["mode"] = self.mode
        return payload

    @property
    def mode(self) -> str:
        return "live" if self.raw.get("live") is True else "dry_run"


@dataclass(kw_only=True, slots=True)
class _RunProgress:
    state: str | None = None
    open_stage: str | None = None
    attempts: dict[str, int] = field(default_factory=dict)
    failure: tuple[str, str] | None = None
    # The outcome and reason of a run that ended without a PR yet did not fail.
    not_delivered: tuple[RunOutcome, str] | None = None


class RunEventMapper:
    """Maps the records of any number of runs, in the order they were written."""

    def __init__(self, *, project: str) -> None:
        self._project = project
        self._runs: dict[str, _RunProgress] = {}

    def map(self, raw: Record) -> tuple[Event, ...]:
        """The events of one record; ``RunRecordError`` when a record field is invalid."""
        record = _checked(raw)
        progress = self._runs.setdefault(record.run, _RunProgress())
        events: list[Event] = []
        if record.state != progress.state:
            events.extend(self._enter(record, progress))
        events.extend(self._on_event(record, progress))
        return tuple(events)

    def _enter(self, record: _Record, progress: _RunProgress) -> list[Event]:
        events: list[Event] = []
        if progress.open_stage is not None and progress.state is not None:
            events.append(self._step_end(record, progress, state=progress.state, status="ok"))
        progress.state = record.state
        key = STAGE_KEYS.get(record.state)
        if key is not None:
            progress.attempts[key] = progress.attempts.get(key, 0) + 1
            progress.open_stage = key
            payload = record.base | {"stage": record.state, "attempt": progress.attempts[key]}
            if record.event == "picked":
                payload["caps"] = _caps(record.raw)
            events.append(self._event(record, EventType.STEP_START, payload, step=key))
        return events

    def _on_event(self, record: _Record, progress: _RunProgress) -> list[Event]:
        if record.event == "gate_ok":
            return [self._gate_passed(record, progress)]
        if record.event == "failed":
            return self._failed(record, progress)
        if record.event == "not_delivered":
            outcome = _outcome(record.raw)
            if outcome in NOT_DELIVERED:
                reason = first_line(text(record.raw, "reason") or "")
                progress.not_delivered = (outcome, reason)
            return []
        if record.event == "reported":
            return [self._run_end(record, progress)]
        return []

    def _gate_passed(self, record: _Record, progress: _RunProgress) -> Event:
        key = STAGE_KEYS.get(record.state, record.state.lower())
        attempt = progress.attempts.get(key, 1)
        payload = record.base | {"gate_id": f"{record.run}:{key}:{attempt}", "kind": GATE_KIND}
        command = text(record.raw, "gate")
        if command is not None:
            payload["command"] = short_text(command, COMMAND_LIMIT)
        payload |= {"result": "passed", "attempt": attempt}
        return self._event(record, EventType.GATE_RESULT, payload, step=key)

    def _failed(self, record: _Record, progress: _RunProgress) -> list[Event]:
        stage = text(record.raw, "stage") or record.state
        reason = first_line(text(record.raw, "reason") or "")
        progress.failure = (stage, reason)
        if progress.open_stage is None or STAGE_KEYS.get(stage) != progress.open_stage:
            return []
        kind = text(record.raw, "failure_kind")
        payload: Payload = {"failure_kind": kind} if kind in FAILURE_KINDS else {}
        return [
            self._step_end(
                record, progress, state=stage, status="failed", reason=reason, extra=payload
            )
        ]

    def _step_end(
        self,
        record: _Record,
        progress: _RunProgress,
        *,
        state: str,
        status: str,
        reason: str | None = None,
        extra: Payload | None = None,
    ) -> Event:
        key = progress.open_stage or STAGE_KEYS[state]
        progress.open_stage = None
        payload = record.base | {
            "stage": state,
            "attempt": progress.attempts.get(key, 1),
            "status": status,
        }
        if reason is not None:
            payload["reason"] = reason
        return self._event(record, EventType.STEP_END, payload | (extra or {}), step=key)

    def _run_end(self, record: _Record, progress: _RunProgress) -> Event:
        failed_stage = text(record.raw, "failed_stage")
        is_done = record.raw.get("ok") is True and failed_stage is None and progress.failure is None
        payload = record.base | {"status": "done" if is_done else "failed"}
        pr_url = text(record.raw, "pr")
        if pr_url is not None:
            payload["pr_url"] = short_text(pr_url, COMMAND_LIMIT)
        cost = record.raw.get("total_cost_usd")
        if isinstance(cost, int | float) and not isinstance(cost, bool):
            payload["cost_usd"] = cost
        if progress.failure is not None:
            payload |= {"stage": progress.failure[0], "reason": progress.failure[1]}
        elif failed_stage is not None:
            payload["stage"] = failed_stage
        outcome = _outcome(record.raw)
        if outcome is None:
            failed = progress.failure is not None or failed_stage is not None
            outcome = RunOutcome.DELIVERED if pr_url and not failed else RunOutcome.FAILED
        payload["outcome"] = outcome.value
        if outcome in NOT_DELIVERED and progress.not_delivered is not None:
            payload["reason"] = progress.not_delivered[1]
        return self._event(record, EventType.RUN_END, payload, step=None)

    def _event(
        self, record: _Record, kind: EventType, payload: Payload, *, step: str | None
    ) -> Event:
        source_id = f"{record.run}:{record.state}:{record.event}:{record.ts}:{kind.value}"
        if kind in {EventType.STEP_START, EventType.STEP_END}:
            source_id = f"{source_id}:{step}"
        return Event(
            project=self._project,
            session=f"{RUN_SESSION_PREFIX}{record.run}",
            type=kind,
            timestamp=record.moment,
            source=EventSource.EXECUTOR,
            source_id=source_id,
            payload=payload,
            repo=text(record.raw, "repo"),
            workflow=RUN_WORKFLOW,
            step=step,
        )


def map_run_records(records: Iterable[Record], *, project: str) -> tuple[Event, ...]:
    """The events of ``records`` (one or more runs, in written order)."""
    mapper = RunEventMapper(project=project)
    return tuple(event for record in records for event in mapper.map(record))


def _checked(raw: Record) -> _Record:
    ts = text(raw, "ts")
    moment = _moment(ts)
    if ts is None or moment is None:
        msg = "ts: expected an ISO 8601 timestamp with an offset"
        raise RunRecordError(msg)
    run = text(raw, "run")
    if run is None:
        msg = "run: expected a non-empty string"
        raise RunRecordError(msg)
    if len(run) > MAX_RUN_CHARS:
        msg = f"run: longer than {MAX_RUN_CHARS} characters"
        raise RunRecordError(msg)
    state = text(raw, "state")
    if state not in set(Stage):
        msg = f"state: expected one of {', '.join(Stage)}"
        raise RunRecordError(msg)
    event = text(raw, "event")
    if event is None:
        msg = "event: expected a non-empty string"
        raise RunRecordError(msg)
    return _Record(raw=raw, ts=ts, moment=moment, run=run, state=state, event=event)


def _moment(ts: str | None) -> datetime | None:
    try:
        moment = datetime.fromisoformat(ts) if ts is not None else None
    except ValueError:
        return None
    return moment if moment is not None and moment.tzinfo is not None else None


def _caps(raw: Record) -> Payload:
    return {key: raw[key] for key in CAPS if isinstance(raw.get(key), str | int | float)}


def _outcome(raw: Record) -> RunOutcome | None:
    """The record's ``outcome`` when it names one, else None."""
    value = text(raw, "outcome")
    try:
        return None if value is None else RunOutcome(value)
    except ValueError:
        return None
