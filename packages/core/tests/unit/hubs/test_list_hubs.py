from datetime import UTC, datetime

import pytest

from agent_hub.core.doctor.snapshot import LockAbsent, LockNotRegular
from agent_hub.core.hub_files.hub_lock import HubLock
from agent_hub.core.hubs.hub_document import HubDocument
from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.hubs.list_hubs import ListHubs, lock_view
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)

RUNNING = "4.5.6"
ADDED = datetime(2026, 10, 9, 14, 0, 0, 123000, tzinfo=UTC)


def a_lock(version: str) -> HubLock:
    return HubLock(lock_version=1, platform_version=version, schema_version=1, modules=(), files={})


def test_views_valid_hub_when_config_valid() -> None:
    registry = InMemoryHubRegistry(clock=lambda: ADDED)
    entry = registry.add("/hubs/demo-hub")
    reader = FakeHubFileReader(
        {"/hubs/demo-hub": FakeHub(hub_json=hub_json_bytes(pin=RUNNING), lock=a_lock(RUNNING))}
    )

    [read] = ListHubs(registry, reader, running_version=RUNNING)()

    view = read.view
    assert (view.id, view.path, view.added_at) == (entry.id, entry.path, ADDED)
    assert view.valid
    assert view.project == "demo"
    assert view.platform_pin == RUNNING
    assert view.running_version == RUNNING
    assert (view.lock_version, view.lock_state) == (RUNNING, "in_sync")
    assert view.repos == ("demo-api",)
    assert view.modules == ("bench", "cloud")
    assert view.warnings == ()


def test_views_invalid_hub_when_hub_json_unreadable() -> None:
    registry = InMemoryHubRegistry()
    registry.add("/hubs/gone")
    reader = FakeHubFileReader()

    [read] = ListHubs(registry, reader, running_version=RUNNING)()

    assert not read.view.valid
    assert read.view.project is None
    assert read.view.validation_errors[0].pointer == ""
    assert read.view.lock_state is None
    assert read.view.repos == ()


def test_warns_when_hub_pinned_to_other_version() -> None:
    registry = InMemoryHubRegistry()
    registry.add("/hubs/old")
    reader = FakeHubFileReader({"/hubs/old": FakeHub(hub_json=hub_json_bytes(pin="0.1.0"))})

    [read] = ListHubs(registry, reader, running_version=RUNNING)()

    assert read.view.valid
    assert read.view.warnings == (f"pinned 0.1.0, running {RUNNING}",)


def test_asks_drift_only_when_lock_matches_pin() -> None:
    registry = InMemoryHubRegistry()
    registry.add("/hubs/demo-hub")
    reader = FakeHubFileReader(
        {"/hubs/demo-hub": FakeHub(hub_json=hub_json_bytes(pin=RUNNING), lock=a_lock(RUNNING))}
    )
    asked: list[str] = []

    def drifted(hub_path: str, document: HubDocument) -> bool:
        asked.append(hub_path)
        return document.valid

    [read] = ListHubs(registry, reader, running_version=RUNNING, has_drift=drifted)()

    assert read.view.lock_state == "drift"
    assert asked == ["/hubs/demo-hub"]


@pytest.mark.parametrize(
    ("lock", "pin", "drift", "expected"),
    [
        (None, RUNNING, False, (None, None)),
        (LockAbsent(), RUNNING, False, ("not_adopted", None)),
        (LockNotRegular(), RUNNING, False, (None, None)),
        ((), RUNNING, False, (None, None)),
        (a_lock("0.1.0"), RUNNING, True, ("sync_pending", "0.1.0")),
        (a_lock(RUNNING), RUNNING, True, ("drift", RUNNING)),
        (a_lock(RUNNING), RUNNING, False, ("in_sync", RUNNING)),
    ],
    ids=["unread", "absent", "not-regular", "problems", "pending", "drift", "in-sync"],
)
def test_names_lock_state_when_lock_read(
    lock: object, pin: str, *, drift: bool, expected: tuple[str | None, str | None]
) -> None:
    assert lock_view(lock, pin=pin, has_drift=lambda: drift) == expected  # type: ignore[arg-type]


def test_reads_not_missing_problem_when_hub_json_folder() -> None:
    registry = InMemoryHubRegistry()
    registry.add("/hubs/odd")
    unread = UnreadHubFile(message="cannot read: not a regular file", is_missing=False)
    reader = FakeHubFileReader({"/hubs/odd": FakeHub(hub_json=unread)})

    [read] = ListHubs(registry, reader, running_version=RUNNING)()

    assert read.view.validation_errors[0].message == unread.message
    assert not read.document.is_missing
