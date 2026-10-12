import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_hub.core.projects.project_views import (
    ActivityItem,
    LiveTile,
    NeedsYouItem,
    ProjectActivity,
    ProjectDetail,
    ProjectNow,
    RepoView,
    SearchHit,
    StreamCounts,
    TrackerView,
)
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.sessions.session import (
    Actor,
    ProblemCounts,
    SessionLabel,
    SessionStatus,
)
from agent_hub.core.testing.read_model_builders import EVENT_ID, HUB_ID, a_project_summary

AT = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def test_serializes_project_summary_with_unconnected_sources_when_dumped() -> None:
    document = json.loads(a_project_summary().model_dump_json())

    assert document["runs_in_flight_by_stage"] == {"IMPLEMENTING": 1}
    assert document["cost_period"] == "1.2734"
    assert (document["open_prs"], document["ready_issues"]) == (None, None)
    assert document["sources_missing"] == ["github", "linear"]


def test_serializes_project_activity_when_dumped() -> None:
    activity = ProjectActivity(
        project="demo",
        live_sessions=2,
        runs_in_flight_by_stage={Stage.VERIFYING: 1},
        failed_runs_7d=1,
        cost_period=Decimal(3),
        cost_previous_period=None,
        cost_daily=(Decimal(1), Decimal(2)),
        last_activity_at=AT,
    )

    document = json.loads(activity.model_dump_json())

    assert document["cost_daily"] == ["1.0000", "2.0000"]


def test_serializes_project_detail_and_now_when_dumped() -> None:
    detail = ProjectDetail(
        name="demo",
        hub_id=HUB_ID,
        hub_path="/home/demo/demo-hub",
        hub_repo="acme/demo-hub",
        tracker=TrackerView(kind="linear", teams=("DEM",), ready_label=None, failed_label=None),
        default_branch="main",
        branch_prefix="jdoe/",
        platform_version="0.8.0",
        lock_version=None,
        lock_state="not_adopted",
        modules=(),
    )
    now = ProjectNow(project="demo", focus=(), next=(), watch=(), source_path=None)

    assert detail.model_dump(mode="json")["tracker"]["teams"] == ["DEM"]
    assert now.model_dump(mode="json")["problem"] is None


def test_rejects_project_detail_when_lock_state_unknown() -> None:
    with pytest.raises(ValidationError, match="lock_state"):
        a_project_summary(lock_state="stale")


def test_serializes_repo_view_when_dumped() -> None:
    repo = RepoView(
        name="demo-api",
        dir="demo-api",
        github="acme/demo-api",
        role=None,
        default_branch="main",
        check_fast="make check-fast",
        check="make check",
        agents_md_present=True,
        agents_md_lines=40,
    )

    assert repo.model_dump(mode="json")["open_prs"] is None


def test_serializes_needs_you_activity_and_search_when_dumped() -> None:
    needs = NeedsYouItem(
        kind="approval", verb="Approve edit", context="demo", project="demo", since=AT, href="/a"
    )
    activity = ActivityItem(kind="failed", text="Run failed", project="demo", at=AT, href=None)
    hit = SearchHit(
        kind="command",
        label="make check",
        detail=None,
        project="demo",
        href="/s",
        event_id=EVENT_ID,
    )

    assert needs.model_dump(mode="json")["since"] == "2026-10-09T14:00:00.000Z"
    assert activity.model_dump(mode="json")["kind"] == "failed"
    assert hit.model_dump(mode="json")["event_id"] == EVENT_ID


def test_serializes_live_tile_and_counts_when_dumped() -> None:
    tile = LiveTile(
        id="session-1",
        project="demo",
        repo=None,
        agent="main",
        status=SessionStatus.WAITING,
        group="waiting",
        last_action="Running make check-fast",
        last_tool="Bash",
        last_activity_at=AT,
        started_at=AT,
        turns=1,
        tokens_total=10,
        files_touched=0,
        errors=0,
        guard_denials=0,
        cost_usd=None,
        sparkline_60s=(0, 2, 1),
    )
    counts = StreamCounts(approvals_open=1, live_sessions=2, failed_runs_7d=0, learnings_proposed=3)

    assert tile.model_dump(mode="json")["sparkline_60s"] == [0, 2, 1]
    assert counts.model_dump(mode="json")["doctor_errors"] is None


def test_serializes_tile_when_label_and_problems_set() -> None:
    tile = LiveTile(
        id="session-1",
        project="demo",
        repo="demo-api",
        agent="main",
        status=SessionStatus.LIVE,
        group="live",
        last_action=None,
        last_tool=None,
        last_activity_at=AT,
        started_at=AT,
        turns=1,
        tokens_total=0,
        files_touched=0,
        errors=1,
        guard_denials=0,
        cost_usd=None,
        label=SessionLabel(
            issue="DEM-7",
            workflow="/feature",
            workflows=("/feature",),
            repo="demo-api",
            branch="roquettejh/dem-7-x",
            worktree=None,
        ),
        actors=(Actor(kind="main"),),
        problems=ProblemCounts(needs_you=1),
        needs_you_problem="Needs you: guard_denied in git push",
    )

    document = json.loads(tile.model_dump_json())

    assert document["label"]["issue"] == "DEM-7"
    assert document["actors"] == [
        {
            "kind": "main",
            "type": None,
            "agent_id": None,
            "description": None,
            "started_by_event_id": None,
        }
    ]
    assert document["problems"]["needs_you"] == 1
    assert document["needs_you_problem"] == "Needs you: guard_denied in git push"
    assert LiveTile.model_json_schema()["properties"]["agent"]["deprecated"] is True
