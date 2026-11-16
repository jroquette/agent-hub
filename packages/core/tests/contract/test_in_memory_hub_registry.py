"""The ``HubRegistry`` contract against the in-memory fake."""

import pytest

from agent_hub.core.hubs.hub_registry import HubRegistry
from agent_hub.core.testing.hub_fakes import InMemoryHubRegistry
from agent_hub.core.testing.hub_registry_contract import HubRegistryContract


@pytest.fixture
def hub_registry() -> HubRegistry:
    return InMemoryHubRegistry()


class TestInMemoryHubRegistry(HubRegistryContract):
    """The fake honours the contract."""
