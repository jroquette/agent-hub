"""Register a hub (D18, Q4): the only write of Phase 2 besides removal.

The path is resolved to its real path first. No ``hub.json`` there is refused as "No hub.json";
one that cannot be read, is no JSON or does not match the schema as "Invalid hub.json" with its
problems' JSON pointers. A pin other than the running release is accepted with a warning. A
path registered already, or a project name another registered hub has, is a conflict.
"""

from agent_hub.core.hubs.hub_document import read_hub_document
from agent_hub.core.hubs.hub_registry import (
    HubConflictError,
    HubFileReader,
    HubInvalidError,
    HubRegistry,
)
from agent_hub.core.hubs.list_hubs import DriftCheck, ListHubs, no_drift
from agent_hub.core.hubs.registered_hub import HubView

NO_HUB_JSON = "No hub.json"
INVALID_HUB_JSON = "Invalid hub.json"


class RegisterHub:
    """Register the hub at a path and return its view."""

    def __init__(
        self,
        registry: HubRegistry,
        reader: HubFileReader,
        *,
        running_version: str,
        has_drift: DriftCheck = no_drift,
    ) -> None:
        self._registry = registry
        self._reader = reader
        self._running = running_version
        self._hubs = ListHubs(
            registry, reader, running_version=running_version, has_drift=has_drift
        )

    def __call__(self, path: str) -> HubView:
        """Register ``path``; ``HubInvalidError`` or ``HubConflictError`` when refused."""
        hub_path = self._reader.resolve(path)
        document = read_hub_document(
            self._reader.read_hub_json(hub_path), running_version=self._running
        )
        if document.is_missing:
            raise HubInvalidError(NO_HUB_JSON, problems=document.problems)
        if not document.valid:
            raise HubInvalidError(INVALID_HUB_JSON, problems=document.problems)
        for other in self._hubs():
            if other.entry.path == hub_path:
                msg = f"the hub at {hub_path!r} is registered already"
                raise HubConflictError(msg)
            if other.document.project == document.project:
                msg = (
                    f"project {document.project!r} is registered already,"
                    f" from the hub at {other.entry.path!r}"
                )
                raise HubConflictError(msg)
        return self._hubs.read(self._registry.add(hub_path)).view
