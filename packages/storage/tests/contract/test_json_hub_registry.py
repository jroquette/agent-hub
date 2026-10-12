"""The ``HubRegistry`` contract against the JSON file adapter, on a file under ``tmp_path``."""

from pathlib import Path

import pytest

from agent_hub.core.hubs.hub_registry import HubRegistry
from agent_hub.core.testing.hub_registry_contract import HubRegistryContract
from agent_hub.storage.hub_registry import JsonHubRegistry


@pytest.fixture
def hub_registry(tmp_path: Path) -> HubRegistry:
    return JsonHubRegistry(tmp_path / "config" / "agent-hub" / "hubs.json")


class TestJsonHubRegistry(HubRegistryContract):
    """The JSON file adapter honours the contract."""
