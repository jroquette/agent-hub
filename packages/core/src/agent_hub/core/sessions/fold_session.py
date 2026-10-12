"""The Session read model, folded from stored events (D12, D14, D16).

``fold_sessions`` is pure: it takes the events and ``now`` and returns the same sessions for
any order of the events and any repeats of them. Only Claude Code sources create a session
(hooks, transcript, OpenTelemetry); executor, GitHub and Linear events never do (AC-200.24),
though an executor run lends its issue to the sessions it started. A session started by
``hub run`` carries ``run``, ``step`` and ``attempt`` from its own events (AC-200.16). Each
session has its ``label`` (issue left for the read models' hub rules) and ``actors`` (AGH-201).
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from agent_hub.core.approvals.fold_approvals import open_gate_ids
from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import canonical_events, canonical_part, resolve_facts
from agent_hub.core.sessions.pricing import PRICES, PerMillion
from agent_hub.core.sessions.session import Outcome, Session, SessionSegment
from agent_hub.core.sessions.session_actors import fold_actors
from agent_hub.core.sessions.session_cost import fold_session_cost, usage_records, usage_tokens
from agent_hub.core.sessions.session_files import fold_session_files
from agent_hub.core.sessions.session_label import label_signals, session_label
from agent_hub.core.sessions.session_status import Activity, session_segments, session_status

SESSION_SOURCES = frozenset({EventSource.CLAUDE_CODE, EventSource.TRANSCRIPT, EventSource.OTEL})
# Fields of a session that only unconnected sources (D15) could fill.
SESSION_SOURCES_MISSING = (EventSource.OTEL, EventSource.GITHUB)
MAIN_AGENT = "main"
_OUTCOMES = frozenset(outcome.value for outcome in Outcome)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _outcome(value: object) -> Outcome | None:
    return Outcome(value) if isinstance(value, str) and value in _OUTCOMES else None


def _activity(stored: StoredEvent) -> Activity:
    event = stored.event
    if event.type != EventType.SESSION_END:
        return Activity(at=event.timestamp)
    return Activity(
        at=event.timestamp,
        ends=True,
        end_reason=_text(event.payload.get("end_reason")),
        outcome=_outcome(event.payload.get("outcome")),
    )


def run_issues(events: Iterable[StoredEvent]) -> dict[str, str]:
    """The issue key of each run, from executor events that name one."""
    issues: dict[str, str] = {}
    for stored in canonical_events(events):
        payload = stored.event.payload
        run, issue = _text(payload.get("run")), _text(payload.get("issue"))
        if stored.event.source == EventSource.EXECUTOR and run and issue:
            issues.setdefault(run, issue)
    return issues


def _attempt(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _run_link(events: Sequence[StoredEvent]) -> tuple[str | None, str | None, int | None]:
    for stored in events:
        run = _text(stored.event.payload.get("run"))
        if run is not None and stored.event.source in SESSION_SOURCES:
            return run, stored.event.step, _attempt(stored.event.payload.get("attempt"))
    return None, None, None


def _agent(events: Sequence[StoredEvent]) -> str:
    for stored in events:
        if stored.event.type == EventType.SESSION_START and stored.event.agent:
            return stored.event.agent
    return MAIN_AGENT


def _turns(events: Sequence[StoredEvent]) -> int:
    transcript_turns = [
        turn
        for stored in events
        if stored.event.source == EventSource.TRANSCRIPT
        and isinstance(turn := stored.event.payload.get("turn"), int)
    ]
    hook_prompts = sum(
        1
        for stored in events
        if stored.event.source == EventSource.CLAUDE_CODE
        and stored.event.type == EventType.MESSAGE
        and stored.event.payload.get("role") == "user"
    )
    return max([hook_prompts, *transcript_turns])


def _has_open_tool_call(winners: Sequence[StoredEvent], events: Sequence[StoredEvent]) -> bool:
    finished = {
        stored.event.payload.get("tool_use_id")
        for stored in events
        if stored.event.type == EventType.TOOL_RESULT
    }
    return any(
        stored.event.type == EventType.TOOL_CALL
        and _text(stored.event.payload.get("tool_use_id")) is not None
        and stored.event.payload.get("tool_use_id") not in finished
        for stored in winners
    )


def _count_results(winners: Sequence[StoredEvent], status: str) -> int:
    return sum(
        1
        for stored in winners
        if stored.event.type == EventType.TOOL_RESULT
        and stored.event.payload.get("status") == status
    )


def _tool_counts(winners: Sequence[StoredEvent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stored in winners:
        tool = _text(stored.event.payload.get("tool"))
        if stored.event.type == EventType.TOOL_CALL and tool is not None:
            counts[tool] = counts.get(tool, 0) + 1
    return counts


def _gates(winners: Sequence[StoredEvent]) -> int:
    gate_types = {EventType.GATE_REQUEST, EventType.GATE_RESULT}
    return len(
        {
            _text(stored.event.payload.get("gate_id")) or stored.event_id
            for stored in winners
            if stored.event.type in gate_types
        }
    )


def _end(
    segments: Sequence[SessionSegment], events: Sequence[StoredEvent]
) -> tuple[Outcome | None, str | None]:
    last = segments[-1] if segments else None
    if last is None or last.ended_at is None or last.end_inferred:
        return None, None if last is None else last.end_reason
    ends = [
        stored
        for stored in events
        if stored.event.type == EventType.SESSION_END and stored.event.timestamp == last.ended_at
    ]
    outcome = _outcome(ends[-1].event.payload.get("outcome")) if ends else None
    return outcome, last.end_reason


def _model(events: Sequence[StoredEvent]) -> str | None:
    models = [record.model for record in usage_records(events) if record.model is not None]
    if models:
        return models[-1]
    for stored in events:
        if stored.event.type == EventType.SESSION_START:
            return _text(stored.event.payload.get("model"))
    return None


def fold_session(
    events: Sequence[StoredEvent],
    *,
    now: datetime,
    issues: Mapping[str, str] | None = None,
    prices: Mapping[str, PerMillion] = PRICES,
) -> Session:
    """One session from its own events (all with the same ``session``; at least one)."""
    ordered = canonical_events(events)
    winners = resolve_facts(ordered).winners
    first = ordered[0].event
    segments = session_segments([_activity(stored) for stored in ordered], now=now)
    outcome, end_reason = _end(segments, ordered)
    run_id, step, attempt = _run_link(ordered)
    cost = fold_session_cost(first.session, ordered, prices=prices)
    records = usage_records(ordered)
    last_at = ordered[-1].event.timestamp
    status = session_status(
        segments,
        last_activity_at=last_at,
        now=now,
        has_open_gate=bool(open_gate_ids(ordered)),
        has_open_tool_call=_has_open_tool_call(winners, ordered),
    )
    return Session(
        id=first.session,
        project=first.project,
        repo=next((stored.event.repo for stored in ordered if stored.event.repo), None),
        agent=_agent(ordered),
        run_id=run_id,
        step=step,
        attempt=attempt,
        issue=None if run_id is None else (issues or {}).get(run_id),
        started_at=first.timestamp,
        ended_at=segments[-1].ended_at,
        last_activity_at=last_at,
        segments=segments,
        status=status,
        outcome=outcome,
        end_reason=end_reason,
        end_inferred=segments[-1].end_inferred,
        turns=_turns(ordered),
        tool_counts=_tool_counts(winners),
        files_touched=len(fold_session_files(winners)),
        errors=_count_results(winners, "error"),
        guard_denials=_count_results(winners, "denied"),
        gates=_gates(winners),
        learnings_proposed=sum(
            1 for stored in winners if stored.event.type == EventType.LEARNING_PROPOSED
        ),
        model=_model(ordered),
        tokens=usage_tokens(records),
        cost_usd=cost.total_usd,
        cost_unknown_reason=cost.unknown_reason,
        has_transcript=any(stored.event.source == EventSource.TRANSCRIPT for stored in ordered),
        label=session_label(label_signals(ordered)),
        actors=fold_actors(ordered),
        sources_missing=SESSION_SOURCES_MISSING,
    )


def group_by_session(events: Iterable[StoredEvent]) -> dict[str, list[StoredEvent]]:
    """The events of each session that exists: one Claude Code source event creates it."""
    groups: dict[str, list[StoredEvent]] = {}
    for stored in canonical_events(events):
        groups.setdefault(stored.event.session, []).append(stored)
    # Each group keeps the canonical order it was taken in.
    return {
        session: canonical_part(group)
        for session, group in groups.items()
        if any(stored.event.source in SESSION_SOURCES for stored in group)
    }


def fold_sessions(
    events: Iterable[StoredEvent],
    *,
    now: datetime,
    prices: Mapping[str, PerMillion] = PRICES,
) -> dict[str, Session]:
    """Every session in ``events``, by id."""
    materialized = list(events)
    issues = run_issues(materialized)
    return {
        session: fold_session(group, now=now, issues=issues, prices=prices)
        for session, group in group_by_session(materialized).items()
    }
