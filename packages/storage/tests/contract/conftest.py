"""The contract suites run here against the SQLite adapters, on a migrated file."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_hub.core.agent_sessions.store import AgentSessionStore
from agent_hub.core.events.event_store import EventStore
from agent_hub.core.item_versions.version_store import ItemVersionStore
from agent_hub.core.knowledge.knowledge_index import KnowledgeIndex
from agent_hub.storage.agent_session_store import open_agent_session_store
from agent_hub.storage.event_store import open_event_store
from agent_hub.storage.item_version_store import open_item_version_store
from agent_hub.storage.knowledge_index import open_knowledge_index


@pytest.fixture
def event_store(tmp_path: Path) -> Iterator[EventStore]:
    store = open_event_store(tmp_path / "events.db")
    yield store
    store.close()


@pytest.fixture
def agent_session_store(tmp_path: Path) -> Iterator[AgentSessionStore]:
    store = open_agent_session_store(tmp_path / "events.db")
    yield store
    store.close()


@pytest.fixture
def item_version_store(tmp_path: Path) -> Iterator[ItemVersionStore]:
    store = open_item_version_store(tmp_path / "events.db")
    yield store
    store.close()


@pytest.fixture
def knowledge_index(tmp_path: Path) -> Iterator[KnowledgeIndex]:
    index = open_knowledge_index(tmp_path / "events.db")
    yield index
    index.close()
