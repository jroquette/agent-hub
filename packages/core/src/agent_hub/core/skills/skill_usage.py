"""How often a project's skills and agents were used, folded from its events (AGH-164, D6, S8, L7).

A pure fold over sessions of stored events: names, counts and times only, never a prompt, an
argument or any other payload text (ADR 0019).

- **Skills.** A signal is a user ``message`` with ``slash_command``, or a ``tool.call`` of the
  ``Skill`` tool with ``skill``. One typed prompt is stored twice (by the hook and by the
  transcript, which share no fact key), and Claude Code may also call ``Skill`` for the same
  invocation, so per session and bare name the signals within ``DEDUPE_WINDOW`` of the first
  signal of the current invocation count once: as ``user`` when any of them is a message, else
  as ``model``.
- **Agents.** A ``tool.call`` of ``Agent`` or ``Task`` with ``subagent_type``, counted from the
  ``resolve_facts`` winners (hook and transcript share ``tool_use_id``), each one a ``model``
  use; no window.

Names are normalised by ``bare_name``. ``fold_skill_uses`` reads the signals at or after a
``start`` into each name's uses (``SkillUses``); ``usage_at`` counts them at a ``now``, keeping
the uses at or after ``now - LONGEST_WINDOW`` (the longest of ``USAGE_WINDOWS``, 90 days);
``fold_skill_usage`` is both, from ``start = now - LONGEST_WINDOW``. ``by_skill`` and
``by_agent`` count only the uses at or after ``now - USAGE_DAYS`` (the Toolkit's 30 days);
``windows_by_skill`` and ``windows_by_agent`` give every name used in 90 days its runs over 7,
30 and 90 days (each window inclusive of its edge) and its last use (AGH-482). At most
``MAX_USAGE_NAMES`` names per kind are kept, the most used first (then by name): the 30-day
maps by 30-day uses (past that ``truncated`` is set), the windows by 90-day uses (past that
``windows_truncated`` is set).

The read model folds the uses once per UTC date and store mark, from that date's midnight minus
90 days, and counts the windows at each read (AGH-611). That equals a fold at the read's ``now``
but for an invocation within ``DEDUPE_WINDOW`` (5 s) of the 90-day edge, which may count
differently: its signals are deduplicated, and its facts resolved, with the ones just before
the edge.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from agent_hub.core.events.event import Event, EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import resolve_facts
from agent_hub.core.skills.skill_view import (
    USAGE_DAYS,
    USAGE_WINDOWS,
    SkillUsage,
    Usage,
    UsageWindows,
    bare_name,
)

DEDUPE_WINDOW: Final = timedelta(seconds=5)
# How far back from its ``now`` a usage read counts.
LONGEST_WINDOW: Final = timedelta(days=max(USAGE_WINDOWS))
MAX_USAGE_NAMES: Final = 500
SKILL_TOOL: Final = "Skill"
AGENT_TOOLS: Final = frozenset({"Agent", "Task"})
_USER_ROLE: Final = "user"


@dataclass(frozen=True, slots=True)
class _Signal:
    name: str
    at: datetime
    typed: bool


@dataclass(frozen=True, slots=True)
class _Use:
    at: datetime
    typed: bool


@dataclass(slots=True)
class _Tally:
    uses: list[_Use] = field(default_factory=list)

    def add(self, *, typed: bool, at: datetime) -> None:
        self.uses.append(_Use(at, typed))


@dataclass(frozen=True, slots=True)
class SkillUses:
    """Each skill's and agent's uses by bare name: when, and whether a person typed it (never
    for an agent). Nothing in it depends on ``now``, so ``usage_at`` counts it at any later one."""

    skills: Mapping[str, tuple[_Use, ...]]
    agents: Mapping[str, tuple[_Use, ...]]


def _name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = bare_name(value.strip())
    return name or None


def _skill_signal(event: Event) -> _Signal | None:
    if event.type == EventType.MESSAGE and event.payload.get("role") == _USER_ROLE:
        name = _name(event.payload.get("slash_command"))
        return None if name is None else _Signal(name, event.timestamp, typed=True)
    if event.type == EventType.TOOL_CALL and event.payload.get("tool") == SKILL_TOOL:
        name = _name(event.payload.get("skill"))
        return None if name is None else _Signal(name, event.timestamp, typed=False)
    return None


def _agent_name(event: Event) -> str | None:
    if event.type != EventType.TOOL_CALL or event.payload.get("tool") not in AGENT_TOOLS:
        return None
    return _name(event.payload.get("subagent_type"))


def _count_invocations(signals: Iterable[_Signal], skills: dict[str, _Tally]) -> None:
    """Add one session's skill signals: per name, the signals within ``DEDUPE_WINDOW`` of an
    invocation's first signal are that invocation."""
    by_name: dict[str, list[_Signal]] = {}
    for signal in signals:
        by_name.setdefault(signal.name, []).append(signal)
    for name, found in by_name.items():
        ordered = sorted(found, key=lambda signal: (signal.at, not signal.typed))
        invocation: list[_Signal] = []
        for signal in ordered:
            if invocation and signal.at - invocation[0].at > DEDUPE_WINDOW:
                _close(name, invocation, skills)
                invocation = []
            invocation.append(signal)
        if invocation:
            _close(name, invocation, skills)


def _close(name: str, invocation: Sequence[_Signal], skills: dict[str, _Tally]) -> None:
    typed = any(signal.typed for signal in invocation)
    tally = skills.setdefault(name, _Tally())
    tally.add(typed=typed, at=max(signal.at for signal in invocation))


def _since(uses: Iterable[_Use], start: datetime) -> list[_Use]:
    return [use for use in uses if use.at >= start]


def _usage(uses: Sequence[_Use]) -> Usage:
    user_count = sum(1 for use in uses if use.typed)
    return Usage(
        count=len(uses),
        user_count=user_count,
        model_count=len(uses) - user_count,
        last_used_at=max(use.at for use in uses),
    )


def _windows(uses: Sequence[_Use], now: datetime) -> UsageWindows:
    runs = [
        sum(1 for use in uses if use.at >= now - timedelta(days=days)) for days in USAGE_WINDOWS
    ]
    runs_7d, runs_30d, runs_90d = runs
    return UsageWindows(
        runs_7d=runs_7d,
        runs_30d=runs_30d,
        runs_90d=runs_90d,
        last_used_at=max(use.at for use in uses),
    )


def _ranked(tallies: Mapping[str, Sequence[_Use]]) -> tuple[list[tuple[str, Sequence[_Use]]], bool]:
    """The ``MAX_USAGE_NAMES`` most used names (then by name) that have a use, sorted by name,
    and whether any was cut."""
    used = [(name, uses) for name, uses in tallies.items() if uses]
    ranked = sorted(used, key=lambda item: (-len(item[1]), item[0]))
    return sorted(ranked[:MAX_USAGE_NAMES]), len(ranked) > MAX_USAGE_NAMES


def _kept(
    uses: Mapping[str, Sequence[_Use]], *, since: datetime, now: datetime
) -> tuple[dict[str, Usage], bool, dict[str, UsageWindows], bool]:
    """Of the uses at or after ``now - LONGEST_WINDOW``: the 30-day usage, capped on the 30-day
    ranking (the Toolkit's), and the windows, capped on the 90-day ranking, each with its own
    cut flag."""
    kept = {name: _since(found, now - LONGEST_WINDOW) for name, found in uses.items()}
    recent, recent_cut = _ranked({name: _since(found, since) for name, found in kept.items()})
    every, every_cut = _ranked(kept)
    usage = {name: _usage(found) for name, found in recent}
    windows = {name: _windows(found, now) for name, found in every}
    return usage, recent_cut, windows, every_cut


def _frozen(tallies: Mapping[str, _Tally]) -> dict[str, tuple[_Use, ...]]:
    return {name: tuple(tally.uses) for name, tally in tallies.items()}


def fold_skill_uses(
    sessions: Mapping[str, Sequence[StoredEvent]], *, project: str, start: datetime
) -> SkillUses:
    """The uses of ``project``'s skills and agents in ``sessions`` (session id -> its events,
    any order), from the signals at or after ``start``."""
    skills: dict[str, _Tally] = {}
    agents: dict[str, _Tally] = {}
    for group in sessions.values():
        events = [
            stored
            for stored in group
            if stored.event.project == project and stored.event.timestamp >= start
        ]
        if not events:
            continue
        winners = [stored.event for stored in resolve_facts(events).winners]
        _count_invocations((s for e in winners if (s := _skill_signal(e)) is not None), skills)
        for event in winners:
            name = _agent_name(event)
            if name is not None:
                agents.setdefault(name, _Tally()).add(typed=False, at=event.timestamp)
    return SkillUses(skills=_frozen(skills), agents=_frozen(agents))


def usage_at(uses: SkillUses, *, now: datetime) -> SkillUsage:
    """The usage of ``uses`` over the ``USAGE_DAYS`` before ``now``, and its 7/30/90-day
    windows, counting only the uses at or after ``now - LONGEST_WINDOW``."""
    since = now - timedelta(days=USAGE_DAYS)
    by_skill, skills_cut, windows_by_skill, skill_windows_cut = _kept(
        uses.skills, since=since, now=now
    )
    by_agent, agents_cut, windows_by_agent, agent_windows_cut = _kept(
        uses.agents, since=since, now=now
    )
    return SkillUsage(
        since=since,
        by_skill=by_skill,
        by_agent=by_agent,
        truncated=skills_cut or agents_cut,
        windows_by_skill=windows_by_skill,
        windows_by_agent=windows_by_agent,
        windows_truncated=skill_windows_cut or agent_windows_cut,
    )


def fold_skill_usage(
    sessions: Mapping[str, Sequence[StoredEvent]], *, project: str, now: datetime
) -> SkillUsage:
    """The usage of ``project``'s skills and agents in ``sessions`` (session id -> its events,
    any order) over the ``USAGE_DAYS`` before ``now``, and its 7/30/90-day windows."""
    uses = fold_skill_uses(sessions, project=project, start=now - LONGEST_WINDOW)
    return usage_at(uses, now=now)
