from agent_hub.core.errors import AgentHubError
from agent_hub.core.hubs.hub_registry import HubFileReader
from agent_hub.core.learnings.brain_change_requests import BrainChangeRequests
from agent_hub.core.learnings.learning_ports import LearningDecisions, LearningReads
from agent_hub.core.readmodels.read_ports import (
    EntityNotFoundError,
    EventReadModels,
    HubReadModels,
)


def test_names_entity_and_id_when_not_found_raised() -> None:
    error = EntityNotFoundError(entity="session", entity_id="abc")

    assert isinstance(error, AgentHubError)
    assert (error.entity, error.entity_id) == ("session", "abc")
    assert str(error) == "no session with id 'abc'"


def test_declares_clarity_methods_when_protocols_inspected() -> None:
    assert callable(EventReadModels.session_problems)
    assert callable(HubReadModels.brain_tree)
    assert callable(HubReadModels.brain_note)
    assert callable(HubFileReader.brain_tree)
    assert callable(HubFileReader.read_brain_file)
    assert callable(HubFileReader.brain_file_size)
    assert callable(LearningReads.list_learnings)
    assert callable(LearningReads.get_learning)
    assert callable(LearningDecisions.accept)
    assert callable(LearningDecisions.reject)
    assert callable(BrainChangeRequests.availability)


def test_declares_feature_tickets_when_protocol_inspected() -> None:
    assert callable(HubReadModels.feature_tickets)
    assert "feature_tickets" in vars(HubReadModels)
