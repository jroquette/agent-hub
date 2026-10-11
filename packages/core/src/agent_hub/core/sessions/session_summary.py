"""The session summary (D17): 3 to 5 deterministic lines, each pointing at the event behind it.

No model writes it: the lines are counted from events (how the session ended, its tool calls
and turns, files edited, then gates or Bash failures, guard denials and learnings proposed, in
that priority). The same events give the same lines in any order. A stored ``session.summary``
event, when the session has one, wins over the computed lines.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime

from agent_hub.core.events.event import EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import canonical_events, resolve_facts
from agent_hub.core.sessions.fold_session import fold_session
from agent_hub.core.sessions.session import Session, SessionSummary, SummaryLine
from agent_hub.core.sessions.session_files import file_operation

MAX_LINES = 5
_EDITS = frozenset({"edited", "created", "written"})


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _of_type(events: Sequence[StoredEvent], type_: EventType) -> list[StoredEvent]:
    return [stored for stored in events if stored.event.type == type_]


def _outcome_line(session: Session, events: Sequence[StoredEvent]) -> SummaryLine:
    last = events[-1]
    if session.ended_at is None:
        return SummaryLine(text=f"Still {session.status.value}", event_id=last.event_id)
    if session.end_inferred:
        at = session.last_activity_at.strftime("%H:%M")
        text = f"Ended without an end event (last activity {at} UTC)"
        return SummaryLine(text=text, event_id=last.event_id)
    ends = _of_type(events, EventType.SESSION_END)
    outcome = session.outcome.value if session.outcome else "without outcome"
    reason = f" ({session.end_reason})" if session.end_reason else ""
    return SummaryLine(text=f"Ended {outcome}{reason}", event_id=(ends or [last])[-1].event_id)


def _activity_line(session: Session, events: Sequence[StoredEvent]) -> SummaryLine:
    calls = sum(session.tool_counts.values())
    text = f"{_plural(calls, 'tool call')} in {_plural(session.turns, 'turn')}"
    return SummaryLine(text=text, event_id=events[0].event_id)


def _files_line(winners: Sequence[StoredEvent], events: Sequence[StoredEvent]) -> SummaryLine:
    edits = [stored for stored in winners if file_operation(stored) in _EDITS]
    paths = {(stored.event.repo, stored.event.payload.get("path")) for stored in edits}
    if not edits:
        return SummaryLine(text="No file edited", event_id=events[0].event_id)
    return SummaryLine(text=f"Edited {_plural(len(paths), 'file')}", event_id=edits[0].event_id)


def _checks_line(winners: Sequence[StoredEvent]) -> SummaryLine | None:
    gates = _of_type(winners, EventType.GATE_RESULT)
    if gates:
        failed = [stored for stored in gates if stored.event.payload.get("result") == "failed"]
        text = f"Gates: {len(gates) - len(failed)} passed, {len(failed)} failed"
        return SummaryLine(text=text, event_id=(failed or gates)[-1].event_id)
    bash = [
        stored
        for stored in _of_type(winners, EventType.TOOL_RESULT)
        if stored.event.payload.get("tool") == "Bash"
        and stored.event.payload.get("status") in {"ok", "error"}
    ]
    if not bash:
        return None
    failed = [stored for stored in bash if stored.event.payload.get("status") == "error"]
    text = f"Bash: {_plural(len(bash), 'command')}, {len(failed)} failed"
    return SummaryLine(text=text, event_id=(failed or bash)[-1].event_id)


def _denials_line(winners: Sequence[StoredEvent]) -> SummaryLine | None:
    denials = [
        stored
        for stored in _of_type(winners, EventType.TOOL_RESULT)
        if stored.event.payload.get("status") == "denied"
    ]
    if not denials:
        return None
    text = f"Guard denied {_plural(len(denials), 'tool call')}"
    return SummaryLine(text=text, event_id=denials[0].event_id)


def _learnings_line(winners: Sequence[StoredEvent]) -> SummaryLine | None:
    proposed = _of_type(winners, EventType.LEARNING_PROPOSED)
    if not proposed:
        return None
    text = f"Proposed {_plural(len(proposed), 'learning')}"
    return SummaryLine(text=text, event_id=proposed[0].event_id)


def _stored_summary(session_id: str, events: Sequence[StoredEvent]) -> SessionSummary | None:
    summaries = _of_type(events, EventType.SESSION_SUMMARY)
    if not summaries:
        return None
    latest = summaries[-1]
    raw = latest.event.payload.get("lines")
    if not isinstance(raw, list):
        text = latest.event.payload.get("text")
        raw = text.splitlines() if isinstance(text, str) else []
    texts = [line.strip() for line in raw if isinstance(line, str) and line.strip()]
    return SessionSummary(
        session_id=session_id,
        lines=tuple(SummaryLine(text=text, event_id=latest.event_id) for text in texts[:MAX_LINES]),
        generated_at=latest.event.timestamp,
        stored=True,
    )


def summarize_session(
    session_id: str, events: Iterable[StoredEvent], *, now: datetime
) -> SessionSummary:
    """The summary of the session whose events are ``events`` (at least one)."""
    ordered = canonical_events(events)
    stored = _stored_summary(session_id, ordered)
    if stored is not None:
        return stored
    session = fold_session(ordered, now=now)
    winners = resolve_facts(ordered).winners
    optional = [_checks_line(winners), _denials_line(winners), _learnings_line(winners)]
    lines = [
        _outcome_line(session, ordered),
        _activity_line(session, ordered),
        _files_line(winners, ordered),
        *(line for line in optional if line is not None),
    ]
    return SessionSummary(
        session_id=session_id,
        lines=tuple(lines[:MAX_LINES]),
        generated_at=ordered[-1].event.timestamp,
    )
