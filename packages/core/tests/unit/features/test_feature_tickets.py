"""The Tickets view of a feature (AGH-136 C.2; AC-136.7, E5, E9)."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_hub.core.errors import TrackerFailure
from agent_hub.core.features import ticket_flow as ticket_flow_module
from agent_hub.core.features.feature_status import FeatureFolder, RecordHead, feature_detail
from agent_hub.core.features.feature_tickets import (
    NOT_CONNECTED_NOTICE,
    NOT_CONNECTED_READ,
    NOT_LOADED_NOTICE,
    PROBLEM_TYPE_PREFIX,
    feature_tickets,
)
from agent_hub.core.features.golden_path import LINEAR_NOT_CONNECTED, LINEAR_NOT_LOADED
from agent_hub.core.features.ticket_records import TicketFiles
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.hub_config.model import Tracker
from agent_hub.core.testing.read_model_builders import READ_TIME
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
    tickets = feature_tickets(
        a_folder(), read, project="demo", tracker=a_tracker(transport), now=READ_TIME
    )

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
    tickets = feature_tickets(
        a_folder(), a_read(), project="demo", tracker=a_tracker(), now=READ_TIME
    )

    assert tickets.source == "plan"
    assert tickets.notice == NOT_LOADED_NOTICE
    assert tickets.notice == "Ticket status from Linear not loaded yet; open the Tickets tab."
    assert tickets.tracker_problem is None
    build = next(step for step in tickets.golden_path.steps if step.name == "build")
    assert build.meta == LINEAR_NOT_LOADED


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

    tickets = feature_tickets(a_folder(), read, project="demo", tracker=a_tracker(), now=READ_TIME)

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

    tickets = feature_tickets(a_folder(), read, project="demo", tracker=a_tracker(), now=READ_TIME)

    assert (tickets.source, tickets.stale, tickets.as_of) == ("linear", True, SNAPSHOT_TIME)
    assert tickets.notice is not None
    assert "may be stale" in tickets.notice
    assert tickets.tracker_problem is not None
    assert tickets.tracker_problem.status == 503
    assert tickets.tickets[0].state is not None


def test_agrees_with_detail_when_snapshot_fresh() -> None:
    read = a_read(snapshot=a_snapshot(), as_of=datetime(2026, 10, 13, 9, 0, tzinfo=UTC))

    tickets = feature_tickets(a_folder(), read, project="demo", tracker=a_tracker(), now=READ_TIME)

    assert (tickets.source, tickets.stale, tickets.notice, tickets.tracker_problem) == (
        "linear",
        False,
        None,
        None,
    )
    assert [row.readiness for row in tickets.tickets] == ["done", "in_progress"]
    assert tickets.planning.can_start == ()
    assert (
        tickets.golden_path
        == feature_detail(a_folder(), project="demo", read=read, now=READ_TIME).golden_path
    )


# two-level-flows AC-1.8: each non-epic row carries its flow, from the folder's records.
def test_serves_ticket_flows_when_folder_has_records() -> None:
    review = b"---\ntype: review\nticket: DEM-7\noutcome: approved\npr: demo-api#3\n---\n"
    folder = replace(
        a_folder(),
        review_round_tickets=("DEM-7",),
        reviews=(RecordHead(name="DEM-7.md", head=review, problem=None),),
    )

    tickets = feature_tickets(
        folder, a_read(snapshot=a_snapshot()), project="demo", tracker=a_tracker(), now=READ_TIME
    )

    first, second = (row.flow for row in tickets.tickets)
    assert first is not None
    assert second is not None
    assert [(step.name, step.state) for step in first.steps] == [
        ("context", "unrecorded"),
        ("preflight", "unrecorded"),
        ("implement", "done"),
        ("review", "done"),
        ("eval", "unrecorded"),
        ("pr", "done"),
        ("merged", "done"),
    ]
    assert first.current == "merged"
    assert {step.state for step in second.steps} == {"pending"}
    assert second.current == "context"


# two-level-flows AC-2.8: the folder's ticket records and change requests reach each row's flow.
def test_serves_preflight_steps_when_folder_has_ticket_records() -> None:
    request = (
        b"---\nticket: DEM-8\nstatus: open\nplan_from: 2\nplan_to: 3\naffected: [T1]\n"
        b"opened_at: 2026-10-21\nrun_id: implement-8\n---\n"
    )
    preflight = {
        "schema": "agent-hub/preflight/1",
        "ticket": "DEM-7",
        "runs": [
            {
                "ran_at": "2026-10-20T09:00:00Z",
                "plan_version": 1,
                "commit": "4e1a9c2",
                "blockers_read": [],
                "input": "none",
                "input_text": None,
                "drift": "none",
                "local_notes": [],
                "change_request": None,
                "run_id": "implement-7",
            }
        ],
    }
    folder = replace(
        a_folder(),
        plan=b"# Plan\n\n## Amendments\n\n- A1 (2026-10-20, Ana): Split the ticket.\n",
        ticket_folders=(
            TicketFiles(name="DEM-7", brief=True, preflight=json.dumps(preflight).encode()),
            TicketFiles(name="DEM-8", brief=True),
        ),
        change_requests=(RecordHead(name="1.md", head=request, problem=None),),
    )
    snapshot = TicketSnapshot(
        summaries=(a_summary("DEM-7", "started"), a_summary("DEM-8", "started")),
        missing=(),
        external=(),
    )

    tickets = feature_tickets(
        folder, a_read(snapshot=snapshot), project="demo", tracker=a_tracker(), now=READ_TIME
    )

    first, second = (row.flow for row in tickets.tickets)
    assert first is not None
    assert second is not None
    assert (first.steps[1].state, first.signal) == ("stale", "Held: plan change pending")
    assert first.steps[1].meta == "Plan v2 approved: re-run preflight"
    assert (second.steps[1].state, second.signal) == ("waiting", "Waiting for you: plan change")
    assert tickets.golden_path.steps[3].signal == "v3 waits for you"


@pytest.mark.parametrize(
    ("read", "meta"),
    [(NOT_CONNECTED_READ, LINEAR_NOT_CONNECTED), (a_read(), LINEAR_NOT_LOADED)],
    ids=["not-connected", "cold"],
)
def test_marks_merged_unknown_when_linear_not_read(read: SnapshotRead, meta: str) -> None:
    tickets = feature_tickets(a_folder(), read, project="demo", tracker=a_tracker(), now=READ_TIME)

    for row in tickets.tickets:
        assert row.flow is not None
        assert (row.flow.steps[-1].state, row.flow.steps[-1].meta) == ("unknown", meta)


# AGH-326 review Q3: the latest verdict is folded once per distinct set of evals, not per row.
def test_folds_eval_verdict_once_when_one_eval_names_every_ticket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = (
        b"---\ntype: eval\ndelivery: dem\nverdict: SHIP\ntickets: [DEM-7, DEM-8]\n"
        b"acs: all\nevaluated_at: 2026-10-10\n---\n"
    )
    folder = replace(a_folder(), evals=(RecordHead(name="dem.md", head=head, problem=None),))
    calls: list[int] = []
    real = ticket_flow_module.latest_verdict

    def counting(records: Any) -> Any:
        calls.append(1)
        return real(records)

    monkeypatch.setattr(ticket_flow_module, "latest_verdict", counting)

    tickets = feature_tickets(
        folder, a_read(snapshot=a_snapshot()), project="demo", tracker=a_tracker(), now=READ_TIME
    )

    assert [row.flow.steps[4].state for row in tickets.tickets if row.flow] == ["done", "done"]
    assert len(calls) == 1
