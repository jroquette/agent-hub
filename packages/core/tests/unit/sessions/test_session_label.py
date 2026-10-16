from datetime import timedelta

import pytest

from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.sessions.session_label import (
    ROUTINE_COMMANDS,
    LabelRules,
    label_signals,
    session_label,
    with_issue,
)
from agent_hub.core.testing.session_scenarios import a_session_events, as_stored, shuffled

MINUTE = timedelta(minutes=1)
TIP = LabelRules(teams=("TIP",), branch_prefix="roquettejh/")


def test_finds_issue_when_branch_has_prefix_and_team() -> None:
    label = session_label(
        label_signals(as_stored(a_session_events(git_branch="roquettejh/demo-1511-fix-login")))
    )

    assert label.issue is None
    assert with_issue(label, TIP).issue == "DEMO-1511"
    assert with_issue(label.model_copy(update={"branch": "tip-7"}), TIP).issue == "TIP-7"


def test_finds_issue_when_worktree_in_cwd_and_no_branch() -> None:
    events = a_session_events(cwd="/work/demo-api/.claude/worktrees/demo-1511-x", git_branch=None)

    label = session_label(label_signals(as_stored(events)))

    assert (label.branch, label.worktree) == (None, "demo-1511-x")
    assert with_issue(label, TIP).issue == "DEMO-1511"


@pytest.mark.parametrize(
    "branch", ["main", "abc-12-x", "roquettejh/abc-12-x", "tip-0-x", "tip-12x", "other/tip-3"]
)
def test_finds_no_issue_when_branch_is_main_or_other_team(branch: str) -> None:
    label = session_label(label_signals(as_stored(a_session_events(git_branch=branch))))

    assert with_issue(label, TIP).issue is None
    assert with_issue(label, LabelRules(teams=(), branch_prefix="")).issue is None


def test_picks_first_workflow_when_prompts_and_skill_used() -> None:
    events = a_session_events(
        slash_commands=("/feature", "/fix"),
        tools=(("Skill", {"skill": "hub-workflow:create-plan"}), ("Read", {"path": "a.py"})),
    )

    label = session_label(label_signals(as_stored(events)))

    assert label.workflow == "/feature"
    assert label.workflows == ("/feature", "/fix", "/create-plan")
    assert label.repo == "demo-api"


def test_skips_routine_command_when_choosing_workflow() -> None:
    assert {"/kickoff", "/clear", "/compact"} <= ROUTINE_COMMANDS
    events = a_session_events(slash_commands=("/kickoff", "/clear", "/fix", "/fix"))

    label = session_label(label_signals(as_stored(events)))

    assert label.workflow == "/fix"
    assert label.workflows == ("/kickoff", "/clear", "/fix")
    only_routine = session_label(
        label_signals(as_stored(a_session_events(slash_commands=("/kickoff",))))
    )
    assert only_routine.workflow == "/kickoff"
    assert session_label(label_signals(as_stored(a_session_events()))).workflow is None


def test_takes_latest_branch_when_branch_changes() -> None:
    first = a_session_events(git_branch="roquettejh/tip-1-old", tools=(), ended=False)
    later = a_session_events(
        git_branch="roquettejh/tip-2-new", tools=(), start=first[-1].timestamp + MINUTE, ended=False
    )
    unnamed = a_session_events(git_branch="", tools=(), start=later[-1].timestamp + MINUTE)
    events = as_stored([*first, *later[1:], *unnamed[1:]])

    for seed in range(20):
        label = session_label(label_signals(shuffled(events, seed)))
        assert label.branch == "roquettejh/tip-2-new"
        assert with_issue(label, TIP).issue == "TIP-2"


def _titled(events: list[Event], *titles: tuple[str, str]) -> list[Event]:
    """``events`` plus one ``session.title`` per (origin, text), a minute apart after the last."""
    last = events[-1]
    return [
        *events,
        *(
            last.model_copy(
                update={
                    "type": EventType.SESSION_TITLE,
                    "source": EventSource.TRANSCRIPT,
                    "source_id": f"title-{index}",
                    "timestamp": last.timestamp + MINUTE * (index + 1),
                    "payload": {"text": text, "origin": origin},
                }
            )
            for index, (origin, text) in enumerate(titles)
        ),
    ]


def test_takes_custom_title_over_newer_ai_title_when_both_exist() -> None:
    events = as_stored(
        _titled(
            a_session_events(),
            ("ai", "First guess"),
            ("custom", "Orders export"),
            ("ai", "Newer guess"),
        )
    )

    for seed in range(10):
        assert session_label(label_signals(shuffled(events, seed))).title == "Orders export"


def test_takes_newest_ai_title_when_no_custom_title() -> None:
    events = as_stored(_titled(a_session_events(), ("ai", "First guess"), ("ai", "Newer guess")))

    assert session_label(label_signals(events)).title == "Newer guess"
    assert session_label(label_signals(as_stored(a_session_events()))).title is None
