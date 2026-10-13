import pytest

from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore
from agent_hub.core.testing.read_model_builders import an_agent_session, an_open_permission


def test_refuses_session_when_id_taken_or_log_not_empty() -> None:
    store = InMemoryAgentSessionStore()
    store.create(an_agent_session(last_seq=0))

    with pytest.raises(ValueError, match="exists"):
        store.create(an_agent_session(last_seq=0))
    with pytest.raises(ValueError, match="last_seq"):
        store.create(an_agent_session(id="01929a4e-7a11-7c00-8a00-00000000a002", last_seq=3))


def test_drops_open_permission_when_stored() -> None:
    store = InMemoryAgentSessionStore()
    session = an_agent_session(last_seq=0, open_permission=an_open_permission())

    store.create(session)

    assert store.get(session.id).open_permission is None
