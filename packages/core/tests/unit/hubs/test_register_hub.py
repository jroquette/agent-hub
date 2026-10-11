import pytest

from agent_hub.core.hubs.hub_registry import HubConflictError, HubInvalidError
from agent_hub.core.hubs.register_hub import RegisterHub
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)

RUNNING = "4.5.6"


def a_register(
    hubs: dict[str, FakeHub], *, aliases: dict[str, str] | None = None
) -> tuple[RegisterHub, InMemoryHubRegistry]:
    registry = InMemoryHubRegistry()
    reader = FakeHubFileReader(hubs, aliases=aliases)
    return RegisterHub(registry, reader, running_version=RUNNING), registry


def test_registers_resolved_path_when_hub_valid() -> None:
    register, registry = a_register(
        {"/real/demo-hub": FakeHub(hub_json=hub_json_bytes(pin=RUNNING))},
        aliases={"~/demo-hub": "/real/demo-hub"},
    )

    view = register("~/demo-hub")

    assert view.path == "/real/demo-hub"
    assert view.project == "demo"
    assert [entry.path for entry in registry.entries()] == ["/real/demo-hub"]


def test_registers_with_warning_when_pinned_to_other_version() -> None:
    register, _ = a_register({"/hubs/old": FakeHub(hub_json=hub_json_bytes(pin="0.1.0"))})

    view = register("/hubs/old")

    assert view.valid
    assert view.warnings == (f"pinned 0.1.0, running {RUNNING}",)


def test_refuses_no_hub_json_when_file_missing() -> None:
    register, registry = a_register({})

    with pytest.raises(HubInvalidError) as raised:
        register("/hubs/empty")

    assert raised.value.title == "No hub.json"
    assert registry.entries() == ()


def test_refuses_with_pointers_when_hub_json_invalid() -> None:
    register, registry = a_register({"/hubs/bad": FakeHub(hub_json=b'{"schema_version": 1}')})

    with pytest.raises(HubInvalidError) as raised:
        register("/hubs/bad")

    assert raised.value.title == "Invalid hub.json"
    assert raised.value.problems
    assert all(problem.pointer.startswith("/") for problem in raised.value.problems)
    assert registry.entries() == ()


def test_refuses_conflict_when_project_registered_elsewhere() -> None:
    register, registry = a_register(
        {
            "/hubs/one": FakeHub(hub_json=hub_json_bytes(pin=RUNNING)),
            "/hubs/two": FakeHub(hub_json=hub_json_bytes(pin=RUNNING)),
        }
    )
    register("/hubs/one")

    with pytest.raises(HubConflictError, match="demo"):
        register("/hubs/two")

    assert len(registry.entries()) == 1


def test_refuses_conflict_when_path_registered_already() -> None:
    register, registry = a_register({"/hubs/one": FakeHub(hub_json=hub_json_bytes(pin=RUNNING))})
    register("/hubs/one")

    with pytest.raises(HubConflictError, match="registered already"):
        register("/hubs/one")

    assert len(registry.entries()) == 1


def test_registers_other_project_when_names_differ() -> None:
    register, registry = a_register(
        {
            "/hubs/one": FakeHub(hub_json=hub_json_bytes(pin=RUNNING)),
            "/hubs/two": FakeHub(hub_json=hub_json_bytes(pin=RUNNING, name="other")),
        }
    )
    register("/hubs/one")

    view = register("/hubs/two")

    assert view.project == "other"
    assert len(registry.entries()) == 2
