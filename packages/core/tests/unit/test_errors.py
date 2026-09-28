import pytest

from agent_hub.core.errors import AgentHubError, EventConflictError


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
