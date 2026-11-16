"""The ``AgentSessionStore`` contract against the in-memory fake."""

import pytest

from agent_hub.core.agent_sessions.store import AgentSessionStore
from agent_hub.core.testing.agent_session_store_contract import AgentSessionStoreContract
from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore


@pytest.fixture
def agent_session_store() -> AgentSessionStore:
    return InMemoryAgentSessionStore()


class TestInMemoryAgentSessionStore(AgentSessionStoreContract):
    """The fake honours the contract."""
