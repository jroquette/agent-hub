from agent_hub.core.agent_sessions.errors import (
    AgentSessionNotFoundError,
    LiveLimitError,
    LogFullError,
    MessageTooLargeError,
    StoreSequenceError,
)
from agent_hub.core.readmodels.read_ports import EntityNotFoundError


def test_maps_to_entity_not_found_when_session_unknown() -> None:
    error = AgentSessionNotFoundError("01929a4e-6c1d-7f3a-9b2e-5d1c0a8e4f17")

    assert isinstance(error, EntityNotFoundError)
    assert error.entity == "agent session"


def test_names_limits_when_raised() -> None:
    assert LiveLimitError(limit=4).limit == 4
    assert "Resume" in str(LogFullError("s-1"))
    assert MessageTooLargeError(size=70_000, limit=65_536).limit == 65_536
    assert StoreSequenceError("s-1", expected=3, got=5).expected == 3
