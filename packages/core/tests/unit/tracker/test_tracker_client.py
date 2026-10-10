import pytest
from pydantic import ValidationError

from agent_hub.core.tracker.tracker_client import (
    ISSUE_ID_PATTERN,
    UNSTARTED_STATE_TYPES,
    Issue,
    TrackerClient,
)

# Spec D1: the port's operations, no more and no fewer.
D1_OPERATIONS = {"list_ready", "get_issue", "move_state", "add_label", "remove_label", "comment"}


def an_issue_value() -> Issue:
    return Issue(
        id="DEM-1",
        title="Add the collector",
        description="Collect the events.",
        state="Todo",
        labels=("agent-ready", "demo-api"),
        url="https://linear.app/demo/issue/DEM-1",
    )


def test_refuses_change_when_issue_field_assigned() -> None:
    issue = an_issue_value()

    with pytest.raises(ValidationError):
        issue.state = "Done"  # type: ignore[misc]

    assert issue.state == "Todo"


def test_holds_labels_as_tuple_when_given_a_list() -> None:
    issue = Issue.model_validate(
        {
            "id": "DEM-1",
            "title": "Add the collector",
            "description": "Collect the events.",
            "state": "Todo",
            "labels": ["agent-ready", "demo-api"],
            "url": "https://linear.app/demo/issue/DEM-1",
        }
    )

    assert issue.labels == ("agent-ready", "demo-api")


def test_requires_description_when_issue_built() -> None:
    fields = an_issue_value().model_dump(exclude={"description"})

    with pytest.raises(ValidationError, match="description"):
        Issue.model_validate(fields)


def test_keeps_description_byte_for_byte_when_issue_built() -> None:
    description = "  Collect\r\nthe \x1b[1mevents\x1b[0m \U0001f600\t\n "

    issue = Issue.model_validate(an_issue_value().model_dump() | {"description": description})

    assert issue.description == description


def test_forbids_extra_field_when_issue_built() -> None:
    fields = an_issue_value().model_dump() | {"body": "x"}

    with pytest.raises(ValidationError):
        Issue.model_validate(fields)


def test_exposes_only_d1_operations_when_port_inspected() -> None:
    public_names = {name for name in vars(TrackerClient) if not name.startswith("_")}

    assert public_names == D1_OPERATIONS


def test_lists_unstarted_types_when_module_read() -> None:
    # Linear's WorkflowState.type values a conditional move_state moves from, as a literal.
    assert UNSTARTED_STATE_TYPES == ("triage", "backlog", "unstarted")


def test_pins_issue_id_bound_when_pattern_read() -> None:
    assert ISSUE_ID_PATTERN.pattern == r"[A-Z][A-Z0-9]{0,9}-[1-9][0-9]{0,8}"


@pytest.mark.parametrize("issue_id", ["A-1", "DEM-1", "ABCDEFGHIJ-999999999"])
def test_accepts_id_when_within_bound(issue_id: str) -> None:
    assert ISSUE_ID_PATTERN.fullmatch(issue_id)


@pytest.mark.parametrize(
    "issue_id", ["ABCDEFGHIJK-1", "DEM-0", "DEM-1234567890", "1EM-1", "DEM-1\n", "dem-1", ""]
)
def test_rejects_id_when_outside_bound(issue_id: str) -> None:
    assert ISSUE_ID_PATTERN.fullmatch(issue_id) is None
