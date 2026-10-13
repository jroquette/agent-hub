from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_hub.core.features.feature_view import GoldenPath, GoldenStep
from agent_hub.core.features.ticket_view import (
    ExternalBlocker,
    FeatureTickets,
    TicketEdge,
    TicketPlan,
    TicketRow,
    TrackerProblem,
)
from agent_hub.core.tracker.tracker_reader import IssueState

_EMPTY_PLAN = TicketPlan(
    layers=(),
    can_start=(),
    order=(),
    waiting=(),
    cycles=(),
    external_blockers=(),
    critical_path=(),
    warnings=(),
)


def _row(**overrides: object) -> TicketRow:
    fields: dict[str, object] = {
        "ref": "TIP-1521",
        "key": "T2",
        "id": "TIP-1521",
        "title": "Read the summaries",
        "state": IssueState(name="Todo", type="unstarted"),
        "assignee": None,
        "url": "https://linear.app/demo/issue/TIP-1521",
        "priority": 2,
        "estimate": None,
        "repo": "demo-api",
        "order": 2,
        "acs": ("AC-7.2",),
        "blocked_by": (TicketEdge(ref="TIP-1520", source="both"),),
        "blocks": (),
        "readiness": "waiting",
        "waiting_on": ("TIP-1520",),
        "reviewed": False,
    }
    return TicketRow.model_validate(fields | overrides)


def test_serializes_tickets_when_planning_empty() -> None:
    tickets = FeatureTickets(
        project="demo",
        slug="demo-feature",
        source="plan",
        stale=False,
        as_of=None,
        notice="From the plan (features.json)",
        tracker_problem=TrackerProblem(
            type="urn:agent-hub:problem:tracker-not_connected",
            title="Linear is not connected",
            status=503,
            detail="LINEAR_API_KEY is not set where hub web runs",
        ),
        tickets=(),
        planning=_EMPTY_PLAN,
        golden_path=GoldenPath(
            steps=(
                GoldenStep(name="spec", state="current", meta=None, reason=None, progress=None),
            ),
            phase="spec",
        ),
    )

    document = tickets.model_dump(mode="json")

    assert document["derived"] is True
    assert (document["source"], document["tickets"], document["planning"]["layers"]) == (
        "plan",
        [],
        [],
    )
    assert document["tracker_problem"]["status"] == 503


def test_serializes_rows_and_planning_when_linear_answered() -> None:
    plan = _EMPTY_PLAN.model_copy(
        update={
            "layers": (("TIP-1520",), ("TIP-1521",)),
            "cycles": (("T5", "T6"),),
            "external_blockers": (
                ExternalBlocker(
                    id="TIP-9",
                    title="Other team's work",
                    state=IssueState(name="Done", type="completed"),
                    url=None,
                    done=True,
                ),
            ),
        }
    )
    tickets = FeatureTickets(
        project="demo",
        slug="demo-feature",
        source="linear",
        stale=True,
        as_of=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
        notice=None,
        tracker_problem=None,
        tickets=(_row(),),
        planning=plan,
        golden_path=GoldenPath(steps=(), phase="spec"),
    )

    document = tickets.model_dump(mode="json")

    assert document["as_of"] == "2026-10-13T09:00:00.000Z"
    assert document["tickets"][0]["blocked_by"] == [{"ref": "TIP-1520", "source": "both"}]
    assert document["planning"]["layers"] == [["TIP-1520"], ["TIP-1521"]]
    assert document["planning"]["external_blockers"][0]["done"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [("readiness", "blocked"), ("blocked_by", ({"ref": "x", "source": "github"},))],
)
def test_rejects_row_when_value_unknown(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        _row(**{field: value})
