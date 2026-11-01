from datetime import UTC, datetime, timedelta

from agent_hub.core.hubs.doctor_cache import DOCTOR_TTL
from agent_hub.core.hubs.hub_snapshot import MIN_RUN_INTERVAL, HubSnapshot, HubState
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)

RUNNING = "4.5.6"
HUB = "/hubs/demo-hub"
START = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def a_hub(**changes: object) -> FakeHub:
    hub = FakeHub(
        hub_json=hub_json_bytes(pin=RUNNING),
        files={"AGENTS.md": b"# Demo\n"},
        mtimes={"hub.json": 1, "hub.lock": 2, "AGENTS.md": 3},
    )
    for name, value in changes.items():
        setattr(hub, name, value)
    return hub


def a_reader(**changes: object) -> FakeHubFileReader:
    return FakeHubFileReader({HUB: a_hub(**changes)})


def a_snapshot(reader: FakeHubFileReader, clock: Clock) -> HubSnapshot:
    registry = InMemoryHubRegistry(clock=clock)
    registry.add(HUB)
    return HubSnapshot(registry, reader, running_version=RUNNING, clock=clock)


def state_of(snapshot: HubSnapshot, path: str) -> HubState:
    [state] = [state for state in snapshot.hubs() if state.read.entry.path == path]
    return state


def test_reuses_check_when_nothing_changed_within_ttl() -> None:
    reader = a_reader()
    clock = Clock()
    snapshot = a_snapshot(reader, clock)

    snapshot.refresh()
    first = state_of(snapshot, HUB).check
    clock.now += DOCTOR_TTL - timedelta(seconds=1)
    snapshot.refresh()
    second = state_of(snapshot, HUB).check

    assert first == second
    assert reader.snapshots == {HUB: 1}


def test_runs_again_when_ttl_passed() -> None:
    reader = a_reader()
    clock = Clock()
    snapshot = a_snapshot(reader, clock)

    snapshot.refresh()
    clock.now += DOCTOR_TTL
    snapshot.refresh()

    assert reader.snapshots == {HUB: 2}


def test_runs_again_when_watched_file_modified() -> None:
    reader = a_reader()
    clock = Clock()
    snapshot = a_snapshot(reader, clock)

    snapshot.refresh()
    reader.hubs[HUB].mtimes["AGENTS.md"] = 99
    clock.now += MIN_RUN_INTERVAL
    snapshot.refresh()

    assert reader.snapshots == {HUB: 2}


def test_runs_again_when_workflow_added() -> None:
    reader = a_reader(
        files={"AGENTS.md": b"# Demo\n", "workflows/demo/lint.yaml": b"x\n"},
        mtimes={"hub.json": 1, "workflows": 4, "workflows/demo": 5},
    )
    clock = Clock()
    snapshot = a_snapshot(reader, clock)

    snapshot.refresh()
    reader.hubs[HUB].mtimes["workflows/demo"] = 6
    clock.now += MIN_RUN_INTERVAL
    snapshot.refresh()

    assert reader.snapshots == {HUB: 2}


def test_runs_again_when_scenario_pack_folder_changes() -> None:
    reader = a_reader(
        scenario_folders=("scenarios/shop",),
        mtimes={"hub.json": 1, "scenarios": 4, "scenarios/shop": 5},
    )
    clock = Clock()
    snapshot = a_snapshot(reader, clock)

    snapshot.refresh()
    reader.hubs[HUB].mtimes["scenarios/shop"] = 6
    clock.now += MIN_RUN_INTERVAL
    snapshot.refresh()

    assert reader.snapshots == {HUB: 2}


def test_runs_again_when_item_folder_changes() -> None:
    # AGH-297: items.leftovers scans the item folders by name, so a temp entry appearing in one
    # (the folder's time) makes the run stale.
    reader = a_reader(item_folders=("plugin/demo/skills",), mtimes={"plugin/demo/skills": 1})
    clock = Clock()
    snapshot = a_snapshot(reader, clock)

    snapshot.refresh()
    reader.hubs[HUB].mtimes["plugin/demo/skills"] = 2
    clock.now += MIN_RUN_INTERVAL
    snapshot.refresh()

    assert reader.snapshots == {HUB: 2}
