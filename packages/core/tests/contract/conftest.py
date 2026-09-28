"""The EventStore contract suite runs here against the in-memory fake."""

import pytest

from agent_hub.core.events.event_store import EventStore
from agent_hub.core.testing.fakes import InMemoryEventStore


@pytest.fixture
def event_store() -> EventStore:
    return InMemoryEventStore()
