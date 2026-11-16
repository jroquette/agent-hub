"""Folds of a whole event history in one call, which the tests use as oracles.

The read models fold incrementally (per session, per UTC date and store mark); these compose
the same production folds over every event at once, so a test can state what the read models
must equal. No production path calls them.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from agent_hub.core.approvals.fold_approvals import fold_approvals
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import canonical_events, canonical_part
from agent_hub.core.sessions.fold_session import SESSION_SOURCES, fold_session, run_issues
from agent_hub.core.sessions.pricing import PRICES, PerMillion
from agent_hub.core.sessions.session import Session
from agent_hub.core.skills.skill_usage import LONGEST_WINDOW, fold_skill_uses, usage_at
from agent_hub.core.skills.skill_view import SkillUsage


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
    """Every session in ``events``, by id: the same for any order and any repeats of them."""
    materialized = list(events)
    issues = run_issues(materialized)
    return {
        session: fold_session(group, now=now, issues=issues, prices=prices)
        for session, group in group_by_session(materialized).items()
    }


def fold_skill_usage(
    sessions: Mapping[str, Sequence[StoredEvent]], *, project: str, now: datetime
) -> SkillUsage:
    """The usage of ``project``'s skills and agents in ``sessions`` (session id -> its events,
    any order) over the ``USAGE_DAYS`` before ``now``, and its 7/30/90-day windows: a fold at
    ``now`` from ``now - LONGEST_WINDOW``."""
    uses = fold_skill_uses(sessions, project=project, start=now - LONGEST_WINDOW)
    return usage_at(uses, now=now)


def open_gate_ids(events: Iterable[StoredEvent]) -> frozenset[str]:
    """The gate ids of the approvals in ``events`` still waiting for a person."""
    return frozenset(
        approval_id
        for approval_id, approval in fold_approvals(events).items()
        if not approval.decided
    )
