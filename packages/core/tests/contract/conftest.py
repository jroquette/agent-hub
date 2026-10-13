"""The core contract suites run here against the in-memory fakes."""

import pytest

from agent_hub.core.events.event_store import EventStore
from agent_hub.core.testing.builders import a_seeded_tracker_backend
from agent_hub.core.testing.fakes import (
    FakeTrackerBackend,
    InMemoryEventStore,
    InMemoryTrackerClient,
)
from agent_hub.core.testing.tracker_reader_fakes import (
    FakeIssueBoard,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)
from agent_hub.core.tracker.tracker_client import TrackerClient
from agent_hub.core.tracker.tracker_reader import TrackerReader


@pytest.fixture
def event_store() -> EventStore:
    return InMemoryEventStore()


@pytest.fixture
def tracker_backend() -> FakeTrackerBackend:
    return a_seeded_tracker_backend()


@pytest.fixture
def tracker_client(tracker_backend: FakeTrackerBackend) -> TrackerClient:
    return InMemoryTrackerClient(tracker_backend)


@pytest.fixture
def issue_board() -> FakeIssueBoard:
    return a_seeded_issue_board()


@pytest.fixture
def tracker_reader(issue_board: FakeIssueBoard) -> TrackerReader:
    return InMemoryTrackerReader(issue_board)
