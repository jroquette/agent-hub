"""The TrackerClient contract suite, run against the Linear GraphQL adapter (AC-9.3).

The adapter's transport is ``FakeLinearApi`` over the suite's ``tracker_backend`` (both from
``tests/conftest.py``), so every write the suite observes went through a GraphQL mutation.
"""

from typing import Any

import pytest

from agent_hub.core.testing.contracts import TrackerClientContract
from agent_hub.core.tracker.tracker_client import TrackerClient
from agent_hub.tracker_linear.graphql import LINEAR_API_KEY_VARIABLE, LinearGraphqlTrackerClient


@pytest.fixture
def tracker_client(fake_linear_api: Any, synthetic_key: str) -> TrackerClient:
    return LinearGraphqlTrackerClient(
        environ={LINEAR_API_KEY_VARIABLE: synthetic_key}, post=fake_linear_api
    )


class TestGraphqlTrackerClient(TrackerClientContract):
    """The TrackerClient contract suite, run against the GraphQL adapter over the fake API."""
