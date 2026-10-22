"""In-memory fakes of the environment discoveries' ports, for core and API tests."""

from collections.abc import Mapping

from agent_hub.core.environment_discovery.discovery import DiscoveryRecord
from agent_hub.core.hub_config.config_view import HubConfigView, hub_config_view
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.builders import an_environments_document

DEMO_HUB_PATH = "/hubs/demo-hub"


def _no_git(_keys: frozenset[str]) -> Mapping[str, str]:
    return {}


def a_demo_config_view() -> HubConfigView:
    """Project ``demo``'s config: ``an_environments_document`` at ``/hubs/demo-hub``."""
    return hub_config_view(
        hub_path=DEMO_HUB_PATH,
        config=HubConfig.model_validate(an_environments_document()),
        local=LocalConfig(),
        read_git=_no_git,
    )


class DemoConfigs:
    """``ProjectConfigs`` with project ``demo`` only."""

    def hub_config(self, project: str) -> HubConfigView:
        """Project ``demo``'s config; ``EntityNotFoundError`` for any other."""
        if project != "demo":
            raise EntityNotFoundError(entity="project", entity_id=project)
        return a_demo_config_view()


class InMemoryDiscoveryRecords:
    """``DiscoveryRecords`` in a dict keyed by hub and id."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], DiscoveryRecord] = {}

    def create(self, hub_path: str, record: DiscoveryRecord) -> None:
        """Store a new record; ``FileExistsError`` when its id is taken."""
        key = (hub_path, record.id)
        if key in self.records:
            raise FileExistsError(record.id)
        self.records[key] = record

    def list(self, hub_path: str) -> tuple[DiscoveryRecord, ...]:
        """The hub's records."""
        return tuple(record for (hub, _), record in self.records.items() if hub == hub_path)

    def get(self, hub_path: str, discovery_id: str) -> DiscoveryRecord | None:
        """One record, or None."""
        return self.records.get((hub_path, discovery_id))

    def replace(self, hub_path: str, record: DiscoveryRecord) -> None:
        """Write a record over its stored self."""
        self.records[(hub_path, record.id)] = record
