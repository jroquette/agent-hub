from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from agent_hub.core.events.event import Event
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.skills import skill_usage
from agent_hub.core.skills.skill_usage import HUB_TOOLS, MAX_USAGE_NAMES, fold_skill_usage
from agent_hub.core.skills.skill_view import USAGE_DAYS, HubToolCalls, Usage, UsageWindows
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import as_stored

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
START = NOW - timedelta(hours=2)


def _at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def _prompt(
    command: str, seconds: float, *, session: str = "s-1", source: str = "claude_code"
) -> Event:
    return an_event(
        session=session,
        type="message",
        timestamp=_at(seconds),
        source=source,
        source_id=f"{session}:{source}:prompt:{seconds}",
        payload={"role": "user", "chars": 9, "slash_command": command},
    )


def _call(
    tool: str,
    payload: dict[str, object],
    seconds: float,
    *,
    tool_use_id: str,
    session: str = "s-1",
    source: str = "claude_code",
) -> Event:
    return an_event(
        session=session,
        type="tool.call",
        timestamp=_at(seconds),
        source=source,
        source_id=f"{session}:{source}:{tool_use_id}",
        payload={"tool": tool, "tool_use_id": tool_use_id, **payload},
    )


def _skill_call(skill: str, seconds: float, *, tool_use_id: str, session: str = "s-1") -> Event:
    return _call("Skill", {"skill": skill}, seconds, tool_use_id=tool_use_id, session=session)


def _sessions(events: Sequence[Event]) -> dict[str, list[StoredEvent]]:
    grouped: dict[str, list[StoredEvent]] = {}
    for stored in as_stored(events):
        grouped.setdefault(stored.event.session, []).append(stored)
    return grouped


def _fold(events: Sequence[Event], *, project: str = "demo") -> dict[str, Usage]:
    return fold_skill_usage(_sessions(events), project=project, now=NOW).by_skill


def test_dedupes_when_hook_and_transcript_report_same_prompt() -> None:
    events = [
        _prompt("/feature", 0),
        _prompt("/feature", 1.5, source="transcript"),
    ]

    usage = _fold(events)

    assert usage == {
        "feature": Usage(count=1, user_count=1, model_count=0, last_used_at=_at(1.5)),
    }


def test_dedupes_when_slash_and_skill_call_within_five_seconds() -> None:
    events = [
        _prompt("/feature", 0),
        _skill_call("hub-workflow:feature", 3, tool_use_id="toolu_skill"),
    ]

    usage = _fold(events)

    assert usage["feature"].model_dump() == {
        "count": 1,
        "user_count": 1,
        "model_count": 0,
        "last_used_at": _at(3),
    }


def test_skips_dedupe_when_signals_six_seconds_apart() -> None:
    events = [
        _prompt("/feature", 0),
        _skill_call("hub-workflow:feature", 6, tool_use_id="toolu_skill"),
        _prompt("/feature", 20),
        _prompt("/feature", 26, source="transcript"),
    ]

    usage = _fold(events)

    feature = usage["feature"]
    assert (feature.count, feature.user_count, feature.model_count) == (4, 3, 1)


def test_counts_apart_when_same_name_in_other_sessions() -> None:
    events = [
        _prompt("/feature", 0, session="s-1"),
        _prompt("/feature", 1, session="s-2"),
    ]

    usage = _fold(events)

    assert usage["feature"].count == 2


def test_counts_agent_once_when_hook_and_transcript_share_tool_use_id() -> None:
    events = [
        _call("Agent", {"subagent_type": "evaluator"}, 0, tool_use_id="toolu_a"),
        _call(
            "Agent",
            {"subagent_type": "evaluator"},
            1,
            tool_use_id="toolu_a",
            source="transcript",
        ),
        _call("Task", {"subagent_type": "hub-workflow:evaluator"}, 2, tool_use_id="toolu_b"),
    ]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.by_agent == {
        "evaluator": Usage(count=2, user_count=0, model_count=2, last_used_at=_at(2)),
    }
    assert usage.by_skill == {}


def test_drops_events_when_older_than_thirty_days() -> None:
    old = NOW - timedelta(days=USAGE_DAYS, seconds=1)
    events = [
        _prompt("/feature", 0),
        an_event(
            session="s-old",
            type="message",
            timestamp=old,
            payload={"role": "user", "slash_command": "/feature"},
        ),
    ]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.by_skill["feature"].count == 1
    assert usage.since == NOW - timedelta(days=USAGE_DAYS)


def test_ignores_events_when_other_project_or_not_a_signal() -> None:
    events = [
        _prompt("/feature", 0, session="s-other").model_copy(update={"project": "other"}),
        an_event(
            session="s-1",
            type="message",
            timestamp=_at(0),
            payload={"role": "assistant", "chars": 3, "slash_command": "/feature"},
        ),
        _call("Bash", {"command": "make check"}, 1, tool_use_id="toolu_bash"),
        _call("Skill", {}, 2, tool_use_id="toolu_noskill"),
        _prompt("/", 3),
    ]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert (usage.by_skill, usage.by_agent, usage.truncated) == ({}, {}, False)


def test_keeps_most_used_when_names_over_cap() -> None:
    events = [_prompt(f"/skill-{n:04d}", n * 10) for n in range(MAX_USAGE_NAMES + 1)]
    events.append(_prompt("/skill-0500", 7_000))

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.truncated
    assert len(usage.by_skill) == MAX_USAGE_NAMES
    assert usage.by_skill["skill-0500"].count == 2
    assert "skill-0499" not in usage.by_skill
    assert "skill-0000" in usage.by_skill


def test_holds_only_names_counts_and_times_when_folded() -> None:
    events = [_prompt("/feature", 0)]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert set(usage.model_dump()) == {
        "since",
        "by_skill",
        "by_agent",
        "truncated",
        "windows_by_skill",
        "windows_by_agent",
        "windows_truncated",
        "hub_tools",
    }
    assert {
        kind: set(windows)
        for kind, windows in usage.hub_tools["mcp__hub__search"].model_dump().items()
    } == {
        "main": {"runs_7d", "runs_30d", "runs_90d", "last_used_at"},
        "subagents": {"runs_7d", "runs_30d", "runs_90d", "last_used_at"},
    }
    assert set(usage.windows_by_skill["feature"].model_dump()) == {
        "runs_7d",
        "runs_30d",
        "runs_90d",
        "last_used_at",
    }
    assert set(usage.by_skill["feature"].model_dump()) == {
        "count",
        "user_count",
        "model_count",
        "last_used_at",
    }


def _prompt_days_ago(days: float, *, session: str) -> Event:
    return an_event(
        session=session,
        type="message",
        timestamp=NOW - timedelta(days=days),
        source_id=f"{session}:prompt:{days}",
        payload={"role": "user", "slash_command": "/feature"},
    )


def test_counts_usage_per_window_when_uses_spread_over_ninety_days() -> None:
    events = [
        _prompt_days_ago(1, session="s-1"),
        _prompt_days_ago(10, session="s-10"),
        _prompt_days_ago(40, session="s-40"),
        _prompt_days_ago(100, session="s-100"),
    ]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.windows_by_skill == {
        "feature": UsageWindows(
            runs_7d=1, runs_30d=2, runs_90d=3, last_used_at=NOW - timedelta(days=1)
        ),
    }
    assert usage.by_skill["feature"].count == 2


def test_counts_usage_at_window_edge_when_use_exactly_seven_days_old() -> None:
    events = [_prompt_days_ago(7, session="s-7")]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    feature = usage.windows_by_skill["feature"]
    assert (feature.runs_7d, feature.runs_30d, feature.runs_90d) == (1, 1, 1)


def test_keeps_thirty_day_usage_when_only_older_uses_exist() -> None:
    events = [_prompt_days_ago(40, session="s-40")]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.by_skill == {}
    assert usage.windows_by_skill["feature"] == UsageWindows(
        runs_7d=0, runs_30d=0, runs_90d=1, last_used_at=NOW - timedelta(days=40)
    )


def test_counts_usage_of_agent_when_parent_agent_call_names_quality_reviewer() -> None:
    events = [
        _call("Agent", {"subagent_type": "quality-reviewer"}, 0, tool_use_id="toolu_q1"),
        _call(
            "Agent",
            {"subagent_type": "quality-reviewer"},
            1,
            tool_use_id="toolu_q1",
            source="transcript",
        ),
        _call("Agent", {"subagent_type": "quality-reviewer"}, 60, tool_use_id="toolu_q2"),
    ]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.windows_by_agent == {
        "quality-reviewer": UsageWindows(runs_7d=2, runs_30d=2, runs_90d=2, last_used_at=_at(60)),
    }


def test_counts_usage_at_window_edge_when_use_exactly_ninety_days_old() -> None:
    events = [
        _prompt_days_ago(90, session="s-90"),
        _prompt_days_ago(90.0001, session="s-older"),
    ]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    feature = usage.windows_by_skill["feature"]
    assert (feature.runs_7d, feature.runs_30d, feature.runs_90d) == (0, 0, 1)


def _named_days_ago(command: str, days: float, *, session: str) -> Event:
    return _prompt_days_ago(days, session=session).model_copy(
        update={"payload": {"role": "user", "slash_command": command}}
    )


def test_keeps_thirty_day_usage_when_ninety_day_names_over_cap() -> None:
    # MAX_USAGE_NAMES names used twice 40 days ago outrank, over 90 days, one name used once
    # yesterday: the windows drop it, the Toolkit's 30-day map keeps it.
    events = [
        _named_days_ago(f"/old-{index:04d}", 40, session=f"s-{index}-{n}")
        for index in range(MAX_USAGE_NAMES)
        for n in range(2)
    ]
    events.append(_named_days_ago("/recent", 1, session="s-recent"))

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.windows_truncated
    assert len(usage.windows_by_skill) == MAX_USAGE_NAMES
    assert "recent" not in usage.windows_by_skill
    assert usage.by_skill == {
        "recent": Usage(count=1, user_count=1, model_count=0, last_used_at=NOW - timedelta(days=1))
    }
    assert not usage.truncated


@pytest.mark.parametrize(
    "events",
    [
        pytest.param(
            [_prompt("/feature", 0), _prompt("/feature", 1.5, source="transcript")],
            id="hook-and-transcript",
        ),
        pytest.param(
            [
                _prompt("/feature", 0),
                _skill_call("hub-workflow:feature", 3, tool_use_id="toolu_skill"),
            ],
            id="slash-and-skill-call",
        ),
        pytest.param(
            [
                _prompt("/feature", 0),
                _skill_call("hub-workflow:feature", 6, tool_use_id="toolu_skill"),
                _prompt("/feature", 20),
                _prompt("/feature", 26, source="transcript"),
            ],
            id="signals-six-seconds-apart",
        ),
        pytest.param(
            [_prompt("/feature", 0, session="s-1"), _prompt("/feature", 1, session="s-2")],
            id="other-sessions",
        ),
        pytest.param(
            [
                _call("Agent", {"subagent_type": "evaluator"}, 0, tool_use_id="toolu_a"),
                _call(
                    "Agent",
                    {"subagent_type": "evaluator"},
                    1,
                    tool_use_id="toolu_a",
                    source="transcript",
                ),
                _call(
                    "Task", {"subagent_type": "hub-workflow:evaluator"}, 2, tool_use_id="toolu_b"
                ),
                _call("Agent", {"subagent_type": "quality-reviewer"}, 60, tool_use_id="toolu_q"),
            ],
            id="agents",
        ),
        pytest.param(
            [
                _prompt("/feature", 0, session="s-other").model_copy(update={"project": "other"}),
                an_event(
                    session="s-1",
                    type="message",
                    timestamp=_at(0),
                    payload={"role": "assistant", "chars": 3, "slash_command": "/feature"},
                ),
                _call("Bash", {"command": "make check"}, 1, tool_use_id="toolu_bash"),
                _call("Skill", {}, 2, tool_use_id="toolu_noskill"),
                _prompt("/", 3),
            ],
            id="other-project-and-not-signals",
        ),
        pytest.param(
            [_prompt_days_ago(days, session=f"s-{days}") for days in (1, 10, 30.0001, 40, 100)],
            id="spread-over-ninety-days",
        ),
        pytest.param(
            [_prompt_days_ago(days, session=f"s-{days}") for days in (7, 30, 90, 90.0001)],
            id="window-edges",
        ),
        pytest.param(
            # A name of its own, so only the read-time 90-day filter keeps it out of the windows.
            [
                _prompt_days_ago(1, session="s-1"),
                _named_days_ago("/early", 90.25, session="s-early"),
            ],
            id="folded-before-ninety-day-edge",
        ),
        pytest.param(
            [
                *(_prompt(f"/skill-{n:04d}", n * 10) for n in range(MAX_USAGE_NAMES + 1)),
                _prompt("/skill-0500", 7_000),
            ],
            id="names-over-cap",
        ),
        pytest.param(
            [
                *(
                    _named_days_ago(f"/old-{index:04d}", 40, session=f"s-{index}-{n}")
                    for index in range(MAX_USAGE_NAMES)
                    for n in range(2)
                ),
                _named_days_ago("/recent", 1, session="s-recent"),
            ],
            id="ninety-day-names-over-cap",
        ),
    ],
)
def test_counts_as_full_fold_when_uses_folded_from_earlier_start(events: list[Event]) -> None:
    sessions = _sessions(events)
    # NOW's UTC midnight minus 90 days: 12 h before NOW's own 90-day edge.
    start = datetime(2026, 10, 13, tzinfo=UTC) - timedelta(days=90)

    uses = skill_usage.fold_skill_uses(sessions, project="demo", start=start)

    assert skill_usage.usage_at(uses, now=NOW) == fold_skill_usage(
        sessions, project="demo", now=NOW
    )


def _hub_call(
    tool: str,
    seconds: float,
    *,
    tool_use_id: str,
    agent: str | None = None,
    agent_id: str | None = None,
    source: str = "claude_code",
) -> Event:
    """A call of a hub knowledge tool (``hub mcp``), by the main agent or by a subagent."""
    payload: dict[str, object] = {"tool": tool, "tool_use_id": tool_use_id, "arg_keys": ["query"]}
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return an_event(
        session="s-1",
        type="tool.call",
        timestamp=_at(seconds),
        source=source,
        source_id=f"s-1:{source}:{tool_use_id}",
        payload=payload,
        agent=agent,
    )


def _windows(runs_7d: int, runs_30d: int, runs_90d: int, at: datetime | None) -> UsageWindows:
    return UsageWindows(runs_7d=runs_7d, runs_30d=runs_30d, runs_90d=runs_90d, last_used_at=at)


NONE_YET = _windows(0, 0, 0, None)


def test_counts_hub_tools_by_main_and_subagent_when_sessions_call_them() -> None:
    events = [
        _hub_call("mcp__hub__search", 0, tool_use_id="toolu_1"),
        # The transcript's copy of the hook's call: one call.
        _hub_call("mcp__hub__search", 1, tool_use_id="toolu_1", source="transcript"),
        _hub_call("mcp__hub__search", 2, tool_use_id="toolu_2", agent="main"),
        _hub_call("mcp__hub__read", 3, tool_use_id="toolu_3"),
        _hub_call("mcp__hub__search", 4, tool_use_id="toolu_4", agent="evaluator", agent_id="a-1"),
        _hub_call("mcp__hub__propose", 5, tool_use_id="toolu_5", agent="planner", agent_id="a-2"),
        _hub_call("mcp__github__search", 6, tool_use_id="toolu_6"),
        _skill_call("feature", 7, tool_use_id="toolu_7"),
    ]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.hub_tools == {
        "mcp__hub__search": HubToolCalls(
            main=_windows(2, 2, 2, _at(2)), subagents=_windows(1, 1, 1, _at(4))
        ),
        "mcp__hub__read": HubToolCalls(main=_windows(1, 1, 1, _at(3)), subagents=NONE_YET),
        "mcp__hub__propose": HubToolCalls(main=NONE_YET, subagents=_windows(1, 1, 1, _at(5))),
    }
    assert "mcp__github__search" not in usage.hub_tools


def test_counts_hub_tools_by_window_when_calls_are_older() -> None:
    old = NOW - timedelta(days=10)
    events = [
        _hub_call("mcp__hub__search", 0, tool_use_id="toolu_1"),
        an_event(
            session="s-2",
            type="tool.call",
            timestamp=old,
            payload={"tool": "mcp__hub__search", "tool_use_id": "toolu_2"},
        ),
        an_event(
            session="s-3",
            type="tool.call",
            timestamp=NOW - timedelta(days=91),
            payload={"tool": "mcp__hub__search", "tool_use_id": "toolu_3"},
        ),
    ]

    usage = fold_skill_usage(_sessions(events), project="demo", now=NOW)

    assert usage.hub_tools["mcp__hub__search"] == HubToolCalls(
        main=_windows(1, 2, 2, _at(0)), subagents=NONE_YET
    )


def test_lists_every_hub_tool_at_zero_when_none_called() -> None:
    usage = fold_skill_usage(_sessions([_prompt("/feature", 0)]), project="demo", now=NOW)

    assert usage.hub_tools == dict.fromkeys(
        HUB_TOOLS, HubToolCalls(main=NONE_YET, subagents=NONE_YET)
    )
    assert HUB_TOOLS == ("mcp__hub__search", "mcp__hub__read", "mcp__hub__propose")
