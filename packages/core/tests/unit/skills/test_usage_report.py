from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from agent_hub.core.events.event import Event
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.skills.skill_usage import fold_skill_usage
from agent_hub.core.skills.skill_view import ItemKind, SkillUsage, UsageDays, UsageWindows
from agent_hub.core.skills.usage_report import ordered_usage, usage_markdown, usage_rows
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.read_model_builders import a_usage_row
from agent_hub.core.testing.session_scenarios import as_stored

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
SKILLS = ((ItemKind.SKILL, "feature"), (ItemKind.SKILL, "refactor"))


def _sessions(events: Sequence[Event]) -> dict[str, list[StoredEvent]]:
    grouped: dict[str, list[StoredEvent]] = {}
    for stored in as_stored(events):
        grouped.setdefault(stored.event.session, []).append(stored)
    return grouped


def _prompt(command: str, *, session: str, hours_ago: float) -> Event:
    return an_event(
        session=session,
        type="message",
        timestamp=NOW - timedelta(hours=hours_ago),
        source_id=f"{session}:prompt",
        payload={"role": "user", "chars": 8, "slash_command": command},
    )


def _agent_call(name: str, *, tool_use_id: str, hours_ago: float) -> Event:
    return an_event(
        session="s-agent",
        type="tool.call",
        timestamp=NOW - timedelta(hours=hours_ago),
        source_id=f"s-agent:{tool_use_id}",
        payload={"tool": "Agent", "tool_use_id": tool_use_id, "subagent_type": name},
    )


def _usage(events: Sequence[Event]) -> SkillUsage:
    return fold_skill_usage(_sessions(events), project="demo", now=NOW)


def test_lists_unused_skill_first_in_usage_when_feature_used_twice() -> None:
    usage = _usage(
        [
            _prompt("/feature", session="s-1", hours_ago=5),
            _prompt("/feature", session="s-2", hours_ago=3),
        ]
    )

    rows = ordered_usage(usage_rows("demo", SKILLS, usage), 30)

    assert [(row.name, row.runs_30d) for row in rows] == [("refactor", 0), ("feature", 2)]
    assert rows[1].last_used_at == NOW - timedelta(hours=3)


def test_shows_agent_usage_with_last_used_when_quality_reviewer_called() -> None:
    usage = _usage(
        [
            _agent_call("quality-reviewer", tool_use_id="toolu_1", hours_ago=30),
            _agent_call("hub-workflow:quality-reviewer", tool_use_id="toolu_2", hours_ago=2),
        ]
    )

    rows = usage_rows("demo", [(ItemKind.AGENT, "quality-reviewer")], usage)

    assert rows == (
        a_usage_row(
            kind=ItemKind.AGENT,
            name="quality-reviewer",
            runs_7d=2,
            runs_30d=2,
            runs_90d=2,
            last_used_at=NOW - timedelta(hours=2),
        ),
    )


def test_gives_zero_usage_when_hub_item_has_no_event() -> None:
    rows = usage_rows("demo", [(ItemKind.SKILL, "refactor")], _usage([]))

    assert rows == (a_usage_row(),)
    assert usage_rows("demo", [(ItemKind.SKILL, "refactor")], None) == (a_usage_row(),)


def test_orders_usage_by_chosen_window_when_days_differ() -> None:
    usage = SkillUsage(
        since=NOW - timedelta(days=30),
        by_skill={},
        by_agent={},
        windows_by_skill={
            "feature": UsageWindows(runs_7d=0, runs_30d=5, runs_90d=5, last_used_at=NOW),
            "review": UsageWindows(runs_7d=1, runs_30d=1, runs_90d=9, last_used_at=NOW),
        },
    )
    rows = usage_rows("demo", [(ItemKind.SKILL, "feature"), (ItemKind.SKILL, "review")], usage)

    def names(days: UsageDays) -> list[str]:
        return [row.name for row in ordered_usage(rows, days)]

    assert names(7) == ["feature", "review"]
    assert names(30) == ["feature", "review"]
    assert names(90) == ["review", "feature"]


def test_prints_usage_markdown_table_when_rows_given() -> None:
    rows = (
        a_usage_row(),
        a_usage_row(
            kind=ItemKind.AGENT,
            name="evaluator",
            runs_7d=1,
            runs_30d=2,
            runs_90d=3,
            last_used_at=datetime(2026, 10, 12, 23, 30, tzinfo=UTC),
        ),
    )

    text = usage_markdown(rows, days=30, truncated=True)

    assert text.splitlines() == [
        "Skills and agents: runs in the last 30 days, never used first.",
        "",
        "| Project | Kind | Name | 7 d | 30 d | 90 d | Last used |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| demo | skill | /refactor | 0 | 0 | 0 | never |",
        "| demo | agent | evaluator | 1 | 2 | 3 | 2026-10-12 |",
        "",
        "Some items were not read; the list may be incomplete.",
    ]
    assert not usage_markdown(rows, days=7, truncated=False).endswith("incomplete.\n")
