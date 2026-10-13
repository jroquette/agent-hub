"""The Tickets view of a feature (AGH-136 C.2; AC-136.7, E5, E9)."""

import json
from datetime import UTC, datetime

import pytest

from agent_hub.core.errors import TrackerFailure
from agent_hub.core.features.feature_status import FeatureFolder, feature_detail
from agent_hub.core.features.feature_tickets import (
    NOT_CONNECTED_NOTICE,
    NOT_CONNECTED_READ,
    NOT_LOADED_NOTICE,
    PROBLEM_TYPE_PREFIX,
    feature_tickets,
)
from agent_hub.core.features.golden_path import LINEAR_NOT_LOADED
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.hub_config.model import Tracker
from agent_hub.core.testing.tracker_reader_fakes import SNAPSHOT_TIME
from agent_hub.core.tracker.tracker_reader import IssueSummary, TicketSnapshot

SENTINEL_KEY = "lin_api_" + "S" * 40


def a_tracker(transport: str = "api") -> Tracker:
    return Tracker.model_validate({"kind": "linear", "team": "DEM", "transport": transport})


def a_folder() -> FeatureFolder:
    record = {
        "tickets": [
            {"key": "T1", "id": "DEM-7", "title": "Collector", "order": 1},
            {"key": "T2", "id": "DEM-8", "title": "Reader", "blocked_by": ["T1"], "order": 2},
        ],
        "acs": [
            {"id": "AC-7.1", "description": "d", "passes": True, "ticket": "T1"},
            {"id": "AC-7.2", "description": "d", "passes": False, "ticket": "T2"},
        ],
    }
    return FeatureFolder(
        slug="demo-feature",
        files=("spec.md", "research.md", "plan.md", "features.json"),
        features_json=json.dumps(record).encode(),
    )


def a_summary(issue_id: str, state_type: str) -> IssueSummary:
    return IssueSummary.model_validate(
        {
            "id": issue_id,
            "title": f"Synthetic {issue_id}",
            "state": {"name": state_type.title(), "type": state_type},
            "assignee": None,
            "url": f"https://linear.app/demo/issue/{issue_id}",
            "priority": 2,
            "estimate": None,
            "blocks": (),
            "blocked_by": (),
        }
    )


def a_read(
    *,
    snapshot: TicketSnapshot | None = None,
    stale: bool = False,
    as_of: datetime | None = None,
    failure: TrackerFailure | None = None,
    detail: str | None = None,
    http_status: int | None = None,
) -> SnapshotRead:
    return SnapshotRead(
        snapshot=snapshot,
        source="plan" if snapshot is None else "linear",
        stale=stale,
        as_of=as_of,
        failure=failure,
        detail=detail,
        http_status=http_status,
    )


def a_snapshot() -> TicketSnapshot:
    return TicketSnapshot(
        summaries=(a_summary("DEM-7", "completed"), a_summary("DEM-8", "started")),
        missing=(),
        external=(),
    )


@pytest.mark.parametrize(
    ("transport", "read"),
    [("mcp", NOT_CONNECTED_READ), ("api", NOT_CONNECTED_READ), ("mcp", a_read())],
    ids=["mcp", "no-key", "mcp-cold"],
)
def test_serves_plan_fallback_when_transport_mcp_or_no_key(
    transport: str, read: SnapshotRead
) -> None:
    tickets = feature_tickets(a_folder(), read, project="demo", tracker=a_tracker(transport))

    assert (tickets.project, tickets.slug, tickets.source) == ("demo", "demo-feature", "plan")
    assert tickets.notice == (
        "From the plan (features.json); Linear is not connected for hub web, so status may be "
        "stale. Set LINEAR_API_KEY where hub web runs."
    )
    assert tickets.notice == NOT_CONNECTED_NOTICE
    assert [(row.ref, row.state, row.reviewed) for row in tickets.tickets] == [
        ("DEM-7", None, None),
        ("DEM-8", None, None),
    ]
    assert (tickets.stale, tickets.as_of) == (False, None)
    assert tickets.tracker_problem is not None
    assert tickets.tracker_problem.type == f"{PROBLEM_TYPE_PREFIX}not_connected"
    assert tickets.tracker_problem.status == 503


def test_says_not_loaded_when_cache_cold() -> None:
    tickets = feature_tickets(a_folder(), a_read(), project="demo", tracker=a_tracker())

    assert tickets.source == "plan"
    assert tickets.notice == NOT_LOADED_NOTICE
    assert tickets.notice == "Ticket status from Linear not loaded yet; open the Tickets tab."
    assert tickets.tracker_problem is None
    shipped = next(step for step in tickets.golden_path.steps if step.name == "shipped")
    assert shipped.meta == LINEAR_NOT_LOADED


@pytest.mark.parametrize(
    ("failure", "http_status", "status"),
    [
        ("unauthorized", 401, 401),
        ("timeout", None, 504),
        ("rate_limited", 429, 429),
        ("unavailable", 500, 500),
        ("unexpected", 200, 502),
        ("unreachable", None, 503),
        ("too_many", None, 503),
    ],
)
def test_names_problem_when_read_failed(
    failure: TrackerFailure, http_status: int | None, status: int
) -> None:
    read = a_read(failure=failure, detail=f"Linear said {SENTINEL_KEY}", http_status=http_status)

    tickets = feature_tickets(a_folder(), read, project="demo", tracker=a_tracker())

    problem = tickets.tracker_problem
    assert problem is not None
    assert problem.type == f"urn:agent-hub:problem:tracker-{failure}"
    assert problem.status == status
    assert problem.title
    assert SENTINEL_KEY not in tickets.model_dump_json()
    assert "[redacted" in problem.detail
    assert tickets.source == "plan"
    assert tickets.notice is not None
    assert tickets.notice.startswith("From the plan (features.json); Linear could not be read")


def test_names_problem_when_stale_snapshot_served() -> None:
    read = a_read(
        snapshot=a_snapshot(),
        stale=True,
        as_of=SNAPSHOT_TIME,
        failure="unavailable",
        detail="HTTP 503 from Linear",
        http_status=503,
    )

    tickets = feature_tickets(a_folder(), read, project="demo", tracker=a_tracker())

    assert (tickets.source, tickets.stale, tickets.as_of) == ("linear", True, SNAPSHOT_TIME)
    assert tickets.notice is not None
    assert "may be stale" in tickets.notice
    assert tickets.tracker_problem is not None
    assert tickets.tracker_problem.status == 503
    assert tickets.tickets[0].state is not None


def test_agrees_with_detail_when_snapshot_fresh() -> None:
    read = a_read(snapshot=a_snapshot(), as_of=datetime(2026, 10, 13, 9, 0, tzinfo=UTC))

    tickets = feature_tickets(a_folder(), read, project="demo", tracker=a_tracker())

    assert (tickets.source, tickets.stale, tickets.notice, tickets.tracker_problem) == (
        "linear",
        False,
        None,
        None,
    )
    assert [row.readiness for row in tickets.tickets] == ["done", "can_start"]
    assert tickets.planning.can_start == ("DEM-8",)
    assert tickets.golden_path == feature_detail(a_folder(), project="demo", read=read).golden_path
