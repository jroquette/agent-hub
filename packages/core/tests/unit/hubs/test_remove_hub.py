import pytest

from agent_hub.core.hubs.remove_hub import RemoveHub
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.hub_fakes import InMemoryHubRegistry


def test_forgets_hub_when_id_registered() -> None:
    registry = InMemoryHubRegistry()
    entry = registry.add("/hubs/demo-hub")

    RemoveHub(registry)(entry.id)

    assert registry.entries() == ()


def test_raises_not_found_when_id_unknown() -> None:
    with pytest.raises(EntityNotFoundError, match="nope"):
        RemoveHub(InMemoryHubRegistry())("nope")
