"""The ``HubRegistry`` contract suite: the in-memory fake and the JSON file adapter honour it.

An implementation's ``tests/contract/`` provides a ``hub_registry`` fixture (an empty registry)
and declares ``class Test<Implementation>(HubRegistryContract)``. Checks raise ``AssertionError``
by hand: core ships this suite without depending on pytest.
"""

import uuid
from datetime import UTC, datetime

from agent_hub.core.hubs.hub_registry import HubConflictError, HubRegistry
from agent_hub.core.readmodels.read_ports import EntityNotFoundError

FIRST = "/hubs/demo-hub"
SECOND = "/hubs/other-hub"
UUID_VERSION = 7


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


class HubRegistryContract:
    """Add, list and remove hubs; a path once; ids are UUIDv7."""

    def test_lists_nothing_when_registry_new(self, hub_registry: HubRegistry) -> None:
        _check(hub_registry.entries() == (), "a new registry lists no hub")

    def test_lists_hubs_in_order_when_added(self, hub_registry: HubRegistry) -> None:
        first = hub_registry.add(FIRST)
        second = hub_registry.add(SECOND)

        _check(hub_registry.entries() == (first, second), "entries are listed as added")
        _check((first.path, second.path) == (FIRST, SECOND), "the path is kept as given")

    def test_mints_uuid7_ids_when_hubs_added(self, hub_registry: HubRegistry) -> None:
        before = datetime.now(UTC)
        first = hub_registry.add(FIRST)
        second = hub_registry.add(SECOND)

        ids = [uuid.UUID(first.id), uuid.UUID(second.id)]
        _check(all(minted.version == UUID_VERSION for minted in ids), "ids are UUIDv7")
        _check(first.id != second.id, "ids are distinct")
        _check(first.added_at.tzinfo is not None, "added_at is aware")
        _check(first.added_at >= before.replace(microsecond=0), "added_at is the add time")

    def test_refuses_path_when_registered_already(self, hub_registry: HubRegistry) -> None:
        first = hub_registry.add(FIRST)

        try:
            hub_registry.add(FIRST)
        except HubConflictError:
            _check(hub_registry.entries() == (first,), "a refused add changes nothing")
            return
        raise AssertionError("expected HubConflictError")

    def test_forgets_hub_when_removed(self, hub_registry: HubRegistry) -> None:
        first = hub_registry.add(FIRST)
        second = hub_registry.add(SECOND)

        hub_registry.remove(first.id)

        _check(hub_registry.entries() == (second,), "only the removed hub is gone")

    def test_adds_path_again_when_removed_before(self, hub_registry: HubRegistry) -> None:
        first = hub_registry.add(FIRST)
        hub_registry.remove(first.id)

        again = hub_registry.add(FIRST)

        _check(again.id != first.id, "a new registration mints a new id")

    def test_raises_not_found_when_id_unknown(self, hub_registry: HubRegistry) -> None:
        hub_registry.add(FIRST)

        try:
            hub_registry.remove("no-such-hub")
        except EntityNotFoundError as error:
            _check(error.entity == "hub", "the entity is a hub")
            _check(error.entity_id == "no-such-hub", "the id is named")
            _check(len(hub_registry.entries()) == 1, "nothing is removed")
            return
        raise AssertionError("expected EntityNotFoundError")
