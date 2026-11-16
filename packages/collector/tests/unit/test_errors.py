from agent_hub.collector.errors import CollectorError
from agent_hub.core.errors import AgentHubError


def test_is_agent_hub_error_when_collector_error_raised() -> None:
    assert issubclass(CollectorError, AgentHubError)
