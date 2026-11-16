import pytest
from pydantic import ValidationError

from agent_hub.core.tracker.tracker_reader import (
    MAX_READ_IDS,
    IssueState,
    IssueSummary,
    TicketSnapshot,
    TrackerReader,
)


def _summary_fields() -> dict[str, object]:
    return {
        "id": "DEM-1",
        "title": "Add the collector",
        "state": IssueState(name="In Progress", type="started"),
        "assignee": "Ada Example",
        "url": "https://linear.app/demo/issue/DEM-1",
        "priority": 2,
        "estimate": 3.0,
        "blocks": ("DEM-2",),
        "blocked_by": (),
    }


def test_refuses_summary_when_field_unknown() -> None:
    with pytest.raises(ValidationError, match="description"):
        IssueSummary.model_validate(_summary_fields() | {"description": "secret body"})


@pytest.mark.parametrize("priority", [0, 4, None])
def test_keeps_priority_range_when_summary_built(priority: int | None) -> None:
    summary = IssueSummary.model_validate(_summary_fields() | {"priority": priority})

    assert summary.priority == priority
    assert summary.relations_truncated is False


@pytest.mark.parametrize("priority", [-1, 5])
def test_refuses_priority_when_out_of_range(priority: int) -> None:
    with pytest.raises(ValidationError, match="priority"):
        IssueSummary.model_validate(_summary_fields() | {"priority": priority})


def test_refuses_state_when_type_unknown() -> None:
    with pytest.raises(ValidationError, match="type"):
        IssueState.model_validate({"name": "Shipped", "type": "shipped"})


def test_holds_missing_and_external_when_snapshot_built() -> None:
    summary = IssueSummary.model_validate(_summary_fields())
    snapshot = TicketSnapshot(summaries=(summary,), missing=("DEM-9",), external=())

    assert (snapshot.summaries[0].id, snapshot.missing) == ("DEM-1", ("DEM-9",))
    assert MAX_READ_IDS == 200
    assert callable(TrackerReader.issue_summaries)
