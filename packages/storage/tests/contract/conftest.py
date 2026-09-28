"""The EventStore contract suite runs here against the SQLite adapter, on a migrated file."""

from pathlib import Path

import pytest

from agent_hub.core.events.event_store import EventStore
from agent_hub.storage.event_store import open_event_store


@pytest.fixture
def event_store(tmp_path: Path) -> EventStore:
    return open_event_store(tmp_path / "events.db")
