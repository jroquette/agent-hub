import pytest

from agent_hub.core.errors import AgentHubError


def test_keeps_message_when_agent_hub_error_raised() -> None:
    with pytest.raises(AgentHubError, match="^something failed$"):
        raise AgentHubError("something failed")
