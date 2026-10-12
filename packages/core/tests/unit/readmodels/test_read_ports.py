from agent_hub.core.errors import AgentHubError
from agent_hub.core.readmodels.read_ports import EntityNotFoundError


def test_names_entity_and_id_when_not_found_raised() -> None:
    error = EntityNotFoundError(entity="session", entity_id="abc")

    assert isinstance(error, AgentHubError)
    assert (error.entity, error.entity_id) == ("session", "abc")
    assert str(error) == "no session with id 'abc'"
