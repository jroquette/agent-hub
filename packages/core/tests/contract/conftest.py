"""The core contract suites run here against the in-memory fakes."""

import pytest

from agent_hub.core.events.event_store import EventStore
from agent_hub.core.item_versions.version_store import ItemVersionStore
from agent_hub.core.testing.builders import a_seeded_tracker_backend
from agent_hub.core.testing.fakes import (
    FakeTrackerBackend,
    InMemoryEventStore,
    InMemoryTrackerClient,
)
from agent_hub.core.testing.hub_item_writer_contract import WriterTree
from agent_hub.core.testing.item_version_fakes import InMemoryItemVersionStore, InMemoryWriterTree
from agent_hub.core.testing.skill_sources_contract import SkillTree
from agent_hub.core.testing.skill_trees import InMemorySkillTree
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


@pytest.fixture
def skill_tree() -> SkillTree:
    return InMemorySkillTree()


@pytest.fixture
def item_version_store() -> ItemVersionStore:
    return InMemoryItemVersionStore()


@pytest.fixture
def writer_tree() -> WriterTree:
    return InMemoryWriterTree()
