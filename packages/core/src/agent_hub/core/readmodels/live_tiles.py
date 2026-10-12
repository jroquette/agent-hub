"""Live sessions tiles: grouped waiting, live, idle and ended in the last 2 minutes.

Order (design spec 11): every waiting tile first, oldest wait first; then live tiles, those
with a failing notice first, then oldest start first; then idle tiles; then sessions ended in
the last 2 minutes, newest end first. Older ended sessions have no tile.

The failing notice (the tile's red edge) appears when the same gate or command failed 2 or
more times in a row, or when 3 or more tool calls failed in the last 5 minutes.

A tile carries its session's label, actors and problem counts (AGH-201), and
``needs_you_problem``: the "what went wrong" line of the first problem that needs the owner.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from agent_hub.core.approvals.approval import Approval, ApprovalKind
from agent_hub.core.approvals.fold_approvals import fold_approvals
from agent_hub.core.events.event import EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.projects.project_views import LiveTile, TileGroup
from agent_hub.core.readmodels.fact_keys import resolve_facts
from agent_hub.core.sessions.problem import Resolution, SessionProblems
from agent_hub.core.sessions.session import Session, SessionStatus
from agent_hub.core.sessions.session_problems import fold_problems

ENDED_RECENTLY = timedelta(minutes=2)
ERROR_WINDOW = timedelta(minutes=5)
STREAK_NOTICE = 2
ERRORS_NOTICE = 3
WAITING_REASONS: Mapping[ApprovalKind, str] = {
    ApprovalKind.GUARD_ASK: "Guard ask",
    ApprovalKind.PLAN: "Plan approval",
    ApprovalKind.SPEC: "Spec approval",
    ApprovalKind.HUMAN_GATE: "Human gate",
    ApprovalKind.PERMISSION: "Permission prompt",
}
_GROUP_ORDER: Mapping[TileGroup, int] = {"waiting": 0, "live": 1, "idle": 2, "ended_recently": 3}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _check_outcomes(winners: Sequence[StoredEvent]) -> list[tuple[str, bool]]:
    """``(gate or command, failed)`` for each gate result and Bash result, in order."""
    commands = {
        stored.event.payload.get("tool_use_id"): _text(stored.event.payload.get("command"))
        for stored in winners
        if stored.event.type == EventType.TOOL_CALL
    }
    outcomes: list[tuple[str, bool]] = []
    for stored in winners:
        payload = stored.event.payload
        if stored.event.type == EventType.GATE_RESULT and payload.get("result") in {
            "passed",
            "failed",
        }:
            name = _text(payload.get("command")) or _text(payload.get("name"))
            if name is not None:
                outcomes.append((name, payload.get("result") == "failed"))
        elif stored.event.type == EventType.TOOL_RESULT and payload.get("status") in {
            "ok",
            "error",
        }:
            command = commands.get(payload.get("tool_use_id"))
            if command is not None:
                outcomes.append((command, payload.get("status") == "error"))
    return outcomes


def _longest_streak(outcomes: Iterable[tuple[str, bool]]) -> tuple[str, int] | None:
    streaks: dict[str, int] = {}
    for name, failed in outcomes:
        streaks[name] = streaks.get(name, 0) + 1 if failed else 0
    if not streaks:
        return None
    name = max(streaks, key=lambda item: streaks[item])
    return name, streaks[name]


def failing_notice(events: Iterable[StoredEvent], *, now: datetime) -> str | None:
    """The tile's failing notice, or None when the session is not failing repeatedly."""
    winners = resolve_facts(events).winners
    streak = _longest_streak(_check_outcomes(winners))
    if streak is not None and streak[1] >= STREAK_NOTICE:
        return f"{streak[0]} failed {streak[1]} times in a row"
    recent_errors = sum(
        1
        for stored in winners
        if stored.event.type == EventType.TOOL_RESULT
        and stored.event.payload.get("status") == "error"
        and now - stored.event.timestamp <= ERROR_WINDOW
    )
    if recent_errors >= ERRORS_NOTICE:
        return f"{recent_errors} tool errors in the last 5 min"
    return None


def _last_action(winners: Sequence[StoredEvent]) -> tuple[str | None, str | None]:
    calls = [stored for stored in winners if stored.event.type == EventType.TOOL_CALL]
    if not calls:
        return None, None
    payload = calls[-1].event.payload
    tool = _text(payload.get("tool"))
    path, command, pattern = (_text(payload.get(key)) for key in ("path", "command", "pattern"))
    if command is not None:
        return f"Ran {command}", tool
    if path is not None:
        verb = "Read" if tool in {"Read", "NotebookRead"} else "Edited"
        return f"{verb} {path}", tool
    if pattern is not None:
        return f"Searched {pattern}", tool
    return (None if tool is None else f"Used {tool}"), tool


def _group(session: Session, now: datetime) -> TileGroup | None:
    if session.status == SessionStatus.WAITING:
        return "waiting"
    if session.status == SessionStatus.LIVE:
        return "live"
    if session.status == SessionStatus.IDLE:
        return "idle"
    if session.ended_at is not None and now - session.ended_at <= ENDED_RECENTLY:
        return "ended_recently"
    return None


def has_tile(session: Session, *, now: datetime) -> bool:
    """Whether ``session`` has a tile at ``now`` (waiting, live, idle or ended recently)."""
    return _group(session, now) is not None


def _open_approvals(events: Sequence[StoredEvent]) -> list[Approval]:
    approvals = fold_approvals(events).values()
    return sorted(
        (approval for approval in approvals if not approval.decided),
        key=lambda approval: approval.requested_at,
    )


def needs_you_line(problems: SessionProblems) -> str | None:
    """The summary line of the first problem that needs the owner, or None when none does."""
    first = next((item for item in problems.items if item.resolution == Resolution.NEEDS_YOU), None)
    if first is None:
        return None
    # The summary puts a counts line first (same event id), then needs-you problems by time.
    return next(
        (line.text for line in problems.summary[1:] if line.event_id == first.event_id), None
    )


def live_tile(
    session: Session,
    events: Sequence[StoredEvent],
    *,
    now: datetime,
    budget_usd: Decimal | None = None,
    problems: SessionProblems | None = None,
) -> LiveTile | None:
    """The tile of ``session`` (whose events are ``events``), or None when it has none.

    ``problems`` are the session's problems at its status; they are folded when not given.
    """
    group = _group(session, now)
    if group is None:
        return None
    if problems is None:
        problems = fold_problems(events, status=session.status)
    winners = resolve_facts(events).winners
    last_action, last_tool = _last_action(winners)
    waiting = _open_approvals(events) if group == "waiting" else []
    tokens = session.tokens
    return LiveTile(
        id=session.id,
        project=session.project,
        repo=session.repo,
        agent=session.agent,
        is_subagent=session.parent_session_id is not None,
        status=session.status,
        group=group,
        outcome=session.outcome,
        waiting_reason=WAITING_REASONS[waiting[0].kind] if waiting else None,
        last_action=last_action,
        last_tool=last_tool,
        last_activity_at=session.last_activity_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
        run_id=session.run_id,
        step=session.step,
        attempt=session.attempt,
        issue=session.issue,
        turns=session.turns,
        tokens_total=0
        if tokens is None
        else tokens.input + tokens.output + tokens.cache_read + tokens.cache_write,
        files_touched=session.files_touched,
        errors=session.errors,
        guard_denials=session.guard_denials,
        cost_usd=session.cost_usd,
        budget_usd=budget_usd,
        failing_notice=failing_notice(events, now=now),
        sources_missing=session.sources_missing,
        label=session.label,
        actors=session.actors,
        problems=session.problems,
        needs_you_problem=needs_you_line(problems),
    )


def _waiting_since(tile: LiveTile, events: Sequence[StoredEvent]) -> datetime:
    waiting = _open_approvals(events)
    return waiting[0].requested_at if waiting else tile.last_activity_at


def _sort_key(tile: LiveTile, events: Sequence[StoredEvent]) -> tuple[int, int, float, str]:
    group = _GROUP_ORDER[tile.group]
    if tile.group == "waiting":
        return (group, 0, _waiting_since(tile, events).timestamp(), tile.id)
    if tile.group == "ended_recently" and tile.ended_at is not None:
        return (group, 0, -tile.ended_at.timestamp(), tile.id)
    failing_first = 0 if tile.failing_notice else 1
    return (group, failing_first, tile.started_at.timestamp(), tile.id)


def live_tiles(
    sessions: Mapping[str, Session],
    events_by_session: Mapping[str, Sequence[StoredEvent]],
    *,
    now: datetime,
    budgets: Mapping[str, Decimal] | None = None,
    problems: Mapping[str, SessionProblems] | None = None,
) -> tuple[LiveTile, ...]:
    """The tiles of ``sessions`` that have one, in the Live sessions order.

    ``problems`` holds the sessions' problems already folded; any other session's are folded.
    """
    tiles: list[LiveTile] = []
    for session_id, session in sessions.items():
        events = events_by_session.get(session_id, ())
        budget = None if session.run_id is None else (budgets or {}).get(session.run_id)
        tile = live_tile(
            session,
            events,
            now=now,
            budget_usd=budget,
            problems=(problems or {}).get(session_id),
        )
        if tile is not None:
            tiles.append(tile)
    return tuple(
        sorted(tiles, key=lambda tile: _sort_key(tile, events_by_session.get(tile.id, ())))
    )
