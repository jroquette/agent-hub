import pytest

from agent_hub.core.errors import AgentHubError, EventConflictError, TrackerError


def test_keeps_message_when_agent_hub_error_raised() -> None:
    with pytest.raises(AgentHubError, match="^something failed$"):
        raise AgentHubError("something failed")


def test_names_key_and_position_when_conflict_error_raised() -> None:
    error = EventConflictError(source="claude_code", source_id="evt-7", position=3)

    assert isinstance(error, AgentHubError)
    assert (error.source, error.source_id, error.position) == ("claude_code", "evt-7", 3)
    assert "claude_code" in str(error)
    assert "evt-7" in str(error)
    assert "3" in str(error)


def test_names_operation_issue_cause_and_fix_when_tracker_error_raised() -> None:
    error = TrackerError(
        operation="move_state",
        issue_id="DEM-1",
        cause="no state named 'Shipped' in team DEM",
        fix="use a state of the team's workflow",
    )

    assert isinstance(error, AgentHubError)
    assert (error.operation, error.issue_id) == ("move_state", "DEM-1")
    assert str(error) == (
        "move_state DEM-1: no state named 'Shipped' in team DEM; use a state of the team's workflow"
    )


def test_omits_issue_id_when_tracker_error_has_none() -> None:
    error = TrackerError(
        operation="list_ready",
        cause="Linear answered HTTP 401",
        fix="check LINEAR_API_KEY",
    )

    assert error.issue_id is None
    assert str(error) == "list_ready: Linear answered HTTP 401; check LINEAR_API_KEY"


def test_stays_on_one_line_when_tracker_error_cause_has_control_characters() -> None:
    error = TrackerError(
        operation="get_issue",
        issue_id="DEM-2",
        cause="unexpected title 'first\nmove_state DEM-3: forged\r\tline\x1b[2J\u2028\u202eend'",
        fix="report it",
    )

    assert all(character.isprintable() for character in str(error))
    assert str(error) == (
        "get_issue DEM-2: unexpected title 'first\\nmove_state DEM-3: forged\\r\\tline"
        "\\x1b[2J\\u2028\\u202eend'; report it"
    )
