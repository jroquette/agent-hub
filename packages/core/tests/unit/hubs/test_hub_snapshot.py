import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_hub.core.doctor.snapshot import DoctorSnapshot, LockState
from agent_hub.core.hubs.doctor_cache import DOCTOR_TTL
from agent_hub.core.hubs.hub_registry import HubRegistryError
from agent_hub.core.hubs.hub_snapshot import MIN_RUN_INTERVAL, HubSnapshot, HubState
from agent_hub.core.hubs.registered_hub import RegisteredHub
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)

RUNNING = "4.5.6"
HUB = "/hubs/demo-hub"
OTHER = "/hubs/other-hub"
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


def an_other_hub(**changes: object) -> FakeHub:
    return a_hub(hub_json=hub_json_bytes(pin=RUNNING, name="other"), **changes)


def a_registry(clock: Clock, *paths: str) -> InMemoryHubRegistry:
    registry = InMemoryHubRegistry(clock=clock)
    for path in paths:
        registry.add(path)
    return registry


def nanoseconds(moment: datetime) -> int:
    """A file time as ``modified_times`` gives it: nanoseconds since the epoch."""
    return int(moment.timestamp()) * 1_000_000_000


def tick(snapshot: HubSnapshot, clock: Clock, *seconds: int) -> None:
    """One refresh at each of ``seconds`` after START, in order, as the refresher's poll."""
    for second in seconds:
        clock.now = START + timedelta(seconds=second)
        snapshot.refresh()


class ScriptedReader(FakeHubFileReader):
    """A reader whose doctor snapshot notes when it ran (by the test's clock), then runs the
    test's action for that hub once, then raises for the hubs in ``failing``."""

    def __init__(self, hubs: dict[str, FakeHub], clock: Clock) -> None:
        super().__init__(hubs)
        self.clock = clock
        self.runs: list[tuple[str, datetime]] = []
        self.failing: set[str] = set()
        self.during_run: dict[str, Callable[[], object]] = {}

    def doctor_snapshot(self, hub_path: str, **kwargs: Any) -> DoctorSnapshot:
        self.runs.append((hub_path, self.clock.now))
        action = self.during_run.pop(hub_path, None)
        if action is not None:
            action()
        if hub_path in self.failing:
            msg = "disk gone"
            raise OSError(msg)
        return super().doctor_snapshot(hub_path, **kwargs)

    def seconds(self, hub_path: str) -> list[int]:
        """When each run of ``hub_path`` started, in seconds after START."""
        return [int((at - START).total_seconds()) for path, at in self.runs if path == hub_path]


def a_hold() -> tuple[threading.Event, threading.Event, Callable[[], object]]:
    """An action that says it started, then waits for the release (5 s at most)."""
    entered = threading.Event()
    release = threading.Event()

    def hold() -> object:
        entered.set()
        return release.wait(timeout=5)

    return entered, release, hold


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


def test_backs_off_doubling_when_runs_keep_failing() -> None:
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub()}, clock)
    reader.failing.add(HUB)
    snapshot = a_snapshot(reader, clock)

    tick(snapshot, clock, *range(0, 3101, 2))
    failed = reader.seconds(HUB)
    reader.failing.clear()
    tick(snapshot, clock, *range(3102, 3981, 2))
    reader.hubs[HUB].mtimes["AGENTS.md"] = 4
    reader.failing.add(HUB)
    tick(snapshot, clock, *range(3982, 4003, 2))

    # A9: the first retry at the next tick, then 10 s after the failure, doubling up to 15 min:
    # gaps 2, 10, 20, 40, 80, 160, 320, 640, 900, 900.
    assert failed == [0, 2, 12, 32, 72, 152, 312, 632, 1272, 2172, 3072]
    # 900 s after the last failure it succeeds; that resets the backoff, so the next failure
    # (a watched file changed 10 s later) is retried at the next tick, then 10 s after.
    assert reader.seconds(HUB)[len(failed) :] == [3972, 3982, 3984, 3994]


def test_waits_min_interval_when_watched_file_changes_soon_after_run() -> None:
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub()}, clock)
    snapshot = a_snapshot(reader, clock)
    tick(snapshot, clock, 0)
    reader.hubs[HUB].mtimes["AGENTS.md"] = 4

    tick(snapshot, clock, 4, 6, 8, 10)

    assert reader.seconds(HUB) == [0, 10]


def test_runs_again_when_watched_file_changes_during_run() -> None:
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub()}, clock)
    snapshot = a_snapshot(reader, clock)
    tick(snapshot, clock, 0)
    mtimes = reader.hubs[HUB].mtimes
    mtimes["AGENTS.md"] = 4

    def written_while_run_reads() -> None:
        mtimes["AGENTS.md"] = 5

    reader.during_run[HUB] = written_while_run_reads

    tick(snapshot, clock, *range(10, 21, 2))

    assert reader.seconds(HUB) == [0, 10, 20]


def test_runs_again_when_path_first_seen_changes_during_first_run() -> None:
    clock = Clock()
    early = {"hub.json": 1, "hub.lock": 2, "AGENTS.md": nanoseconds(START - timedelta(seconds=2))}
    reader = ScriptedReader({HUB: a_hub(), OTHER: an_other_hub(mtimes=early)}, clock)
    mtimes = reader.hubs[HUB].mtimes

    def written_as_run_starts() -> None:
        mtimes["AGENTS.md"] = nanoseconds(START)

    reader.during_run[HUB] = written_as_run_starts
    snapshot = HubSnapshot(
        a_registry(clock, HUB, OTHER), reader, running_version=RUNNING, clock=clock
    )

    tick(snapshot, clock, *range(0, 11, 2))

    assert reader.seconds(HUB) == [0, 10]
    assert reader.seconds(OTHER) == [0]


class BreakableRegistry(InMemoryHubRegistry):
    """A registry whose file can be made unreadable."""

    def __init__(self, clock: Clock) -> None:
        super().__init__(clock=clock)
        self.broken = False

    def entries(self) -> tuple[RegisteredHub, ...]:
        if self.broken:
            msg = "cannot read the hub registry"
            raise HubRegistryError(msg)
        return super().entries()


def test_raises_registry_error_and_keeps_checks_when_registry_cannot_be_read() -> None:
    clock = Clock()
    reader = a_reader()
    registry = BreakableRegistry(clock)
    registry.add(HUB)
    registry.broken = True
    snapshot = HubSnapshot(registry, reader, running_version=RUNNING, clock=clock)

    with pytest.raises(HubRegistryError):
        snapshot.hubs()
    registry.broken = False
    snapshot.refresh()
    checked = state_of(snapshot, HUB).check
    assert checked is not None
    registry.broken = True
    clock.now += timedelta(seconds=2)
    with pytest.raises(HubRegistryError):
        snapshot.refresh()
    with pytest.raises(HubRegistryError):
        snapshot.hubs()
    registry.broken = False
    clock.now += timedelta(seconds=2)
    snapshot.refresh()

    assert state_of(snapshot, HUB).check == checked
    assert reader.snapshots == {HUB: 1}


class HeldLockReader(FakeHubFileReader):
    """A reader whose next ``read_lock`` call, once ``armed``, waits for the release."""

    def __init__(self, hubs: dict[str, FakeHub]) -> None:
        super().__init__(hubs)
        self.armed = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def read_lock(self, hub_path: str) -> LockState | None:
        if self.armed:
            self.armed = False
            self.entered.set()
            self.release.wait(timeout=5)
        return super().read_lock(hub_path)


def test_keeps_hub_added_by_reread_when_tick_publishes_after_it() -> None:
    clock = Clock()
    reader = HeldLockReader({HUB: a_hub(), OTHER: an_other_hub()})
    registry = a_registry(clock, HUB)
    snapshot = HubSnapshot(registry, reader, running_version=RUNNING, clock=clock)
    assert [state.read.entry.path for state in snapshot.hubs()] == [HUB]
    reader.hubs[HUB].mtimes["hub.lock"] = 7
    reader.armed = True
    ticking = threading.Thread(target=snapshot.refresh)
    ticking.start()
    assert reader.entered.wait(timeout=5)

    registry.add(OTHER)
    rereading = threading.Thread(target=snapshot.reread)
    rereading.start()
    # A reread that does not wait for the tick's writer lock ends within this wait.
    rereading.join(timeout=0.5)
    reader.release.set()
    ticking.join(timeout=5)
    rereading.join(timeout=5)

    assert not ticking.is_alive()
    assert not rereading.is_alive()
    assert [state.read.entry.path for state in snapshot.hubs()] == [HUB, OTHER]


def test_drops_check_of_removed_hub_when_its_run_ends_after_removal() -> None:
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub()}, clock)
    entered, release, hold = a_hold()
    reader.during_run[HUB] = hold
    registry = InMemoryHubRegistry(clock=clock)
    entry = registry.add(HUB)
    snapshot = HubSnapshot(registry, reader, running_version=RUNNING, clock=clock)
    ticking = threading.Thread(target=snapshot.refresh)
    ticking.start()
    assert entered.wait(timeout=5)

    registry.remove(entry.id)
    snapshot.reread()
    release.set()
    ticking.join(timeout=5)

    assert not ticking.is_alive()
    assert snapshot.hubs() == ()
    registry.add(HUB)
    snapshot.reread()
    [state] = snapshot.hubs()
    assert state.check is None
