"""Forget a registered hub (D18); its events stay in the store."""

from agent_hub.core.hubs.hub_registry import HubRegistry


class RemoveHub:
    """Remove a hub from the registry by id."""

    def __init__(self, registry: HubRegistry) -> None:
        self._registry = registry

    def __call__(self, hub_id: str) -> None:
        """Forget the hub; ``EntityNotFoundError`` when no hub has the id."""
        self._registry.remove(hub_id)
