from agent_hub.core.errors import AgentHubError
from agent_hub.storage.errors import StorageError


def test_is_agent_hub_error_when_storage_error_raised() -> None:
    assert issubclass(StorageError, AgentHubError)
