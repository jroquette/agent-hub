"""The ``BrainChangeRequests`` contract against the in-memory fake."""

import pytest

from agent_hub.core.learnings.brain_change_requests import BrainChangeRequests
from agent_hub.core.testing.brain_change_requests_contract import BrainChangeRequestsContract
from agent_hub.core.testing.brain_fakes import FakeBrainOrigin, InMemoryBrainChangeRequests


@pytest.fixture
def brain_origin() -> FakeBrainOrigin:
    return FakeBrainOrigin()


@pytest.fixture
def brain_change_requests(brain_origin: FakeBrainOrigin) -> BrainChangeRequests:
    return InMemoryBrainChangeRequests(brain_origin)


class TestInMemoryBrainChangeRequests(BrainChangeRequestsContract):
    """The fake honours the contract."""
