from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from agent_hub.core.events.event import Event
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.skills.skill_usage import MAX_USAGE_NAMES, fold_skill_usage
from agent_hub.core.skills.skill_view import USAGE_DAYS, Usage
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


def test_counts_once_when_hook_and_transcript_report_same_prompt() -> None:
    events = [
        _prompt("/feature", 0),
        _prompt("/feature", 1.5, source="transcript"),
    ]

    usage = _fold(events)

    assert usage == {
        "feature": Usage(count=1, user_count=1, model_count=0, last_used_at=_at(1.5)),
    }


def test_counts_once_when_slash_and_skill_call_within_five_seconds() -> None:
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


def test_counts_twice_when_signals_six_seconds_apart() -> None:
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

    assert set(usage.model_dump()) == {"since", "by_skill", "by_agent", "truncated"}
    assert set(usage.by_skill["feature"].model_dump()) == {
        "count",
        "user_count",
        "model_count",
        "last_used_at",
    }
