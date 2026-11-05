import json
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_hub.core.doctor.snapshot import DoctorSnapshot, LockAbsent, LockState
from agent_hub.core.hub_config.doctor_rules import CONFIG_SCHEMA_RULE
from agent_hub.core.hub_files.hub_lock import HubLock
from agent_hub.core.hubs.doctor_cache import DOCTOR_TTL
from agent_hub.core.hubs.hub_document import read_hub_document
from agent_hub.core.hubs.hub_registry import HubRegistryError, UnreadHubFile
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


def a_lock() -> HubLock:
    return HubLock(lock_version=1, platform_version=RUNNING, schema_version=1, modules=(), files={})


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


def a_hold() -> tuple[threading.Event, threading.Event, threading.Event, Callable[[], object]]:
    """An action that sets ``entered``, then waits for ``release``, 5 s at most. It runs inside
    the doctor run, where a raise would only become a refresh failure, so a wait that ends
    without the release sets ``timed_out`` instead; each test that holds a run asserts, on its
    own thread after the join, that it is not set."""
    entered = threading.Event()
    release = threading.Event()
    timed_out = threading.Event()

    def hold() -> None:
        entered.set()
        if not release.wait(timeout=5):
            timed_out.set()

    return entered, release, timed_out, hold


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


def test_lists_registered_hubs_without_check_when_never_refreshed() -> None:
    reader = a_reader(lock=a_lock())
    snapshot = a_snapshot(reader, Clock())

    [state] = snapshot.hubs()

    assert state.read.entry.path == HUB
    assert state.check is None
    # A lock matching the pin needs the doctor's lock.drift to be named: unknown until a check.
    assert (state.read.view.lock_state, state.read.view.lock_version) == (None, RUNNING)
    assert reader.snapshots == {}


def test_stamps_check_with_clock_at_end_of_run_when_refreshed() -> None:
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub()}, clock)

    def three_seconds_pass() -> None:
        clock.now += timedelta(seconds=3)

    reader.during_run[HUB] = three_seconds_pass
    snapshot = a_snapshot(reader, clock)

    snapshot.refresh()

    check = state_of(snapshot, HUB).check
    assert check is not None
    assert check.checked_at == START + timedelta(seconds=3)
    assert reader.seconds(HUB) == [0]


def test_keeps_previous_check_and_runs_again_when_run_raises() -> None:
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub()}, clock)
    snapshot = a_snapshot(reader, clock)
    tick(snapshot, clock, 0)
    before = state_of(snapshot, HUB).check
    assert before is not None
    reader.hubs[HUB].mtimes["AGENTS.md"] = 4
    reader.failing.add(HUB)
    clock.now = START + timedelta(seconds=10)

    report = snapshot.refresh()
    kept = state_of(snapshot, HUB).check
    reader.failing.clear()
    tick(snapshot, clock, 12)

    assert [failure.hub_path for failure in report.failures] == [HUB]
    assert kept == before
    assert before.checked_at == START
    again = state_of(snapshot, HUB).check
    assert again is not None
    assert again.checked_at == START + timedelta(seconds=12)
    assert reader.seconds(HUB) == [0, 10, 12]


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


def test_shows_new_hub_without_check_when_reread_after_registration() -> None:
    clock = Clock()
    reader = FakeHubFileReader({HUB: a_hub(), OTHER: an_other_hub()})
    registry = a_registry(clock, HUB)
    snapshot = HubSnapshot(registry, reader, running_version=RUNNING, clock=clock)
    snapshot.refresh()

    registry.add(OTHER)
    snapshot.reread()

    states = snapshot.hubs()
    assert [state.read.entry.path for state in states] == [HUB, OTHER]
    assert states[0].check is not None
    assert states[1].check is None
    assert reader.snapshots == {HUB: 1}


def test_drops_hub_when_reread_after_removal() -> None:
    clock = Clock()
    reader = FakeHubFileReader({HUB: a_hub(), OTHER: an_other_hub()})
    registry = a_registry(clock, HUB)
    other = registry.add(OTHER)
    snapshot = HubSnapshot(registry, reader, running_version=RUNNING, clock=clock)
    snapshot.refresh()
    assert len(snapshot.hubs()) == 2

    registry.remove(other.id)
    snapshot.reread()

    assert [state.read.entry.path for state in snapshot.hubs()] == [HUB]


def test_publishes_first_hub_check_when_second_run_is_held() -> None:
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub(), OTHER: an_other_hub()}, clock)
    entered, release, timed_out, hold = a_hold()
    reader.during_run[OTHER] = hold
    snapshot = HubSnapshot(
        a_registry(clock, HUB, OTHER), reader, running_version=RUNNING, clock=clock
    )
    ticking = threading.Thread(target=snapshot.refresh)
    ticking.start()
    assert entered.wait(timeout=5)

    held = {state.read.entry.path: state.check for state in snapshot.hubs()}
    release.set()
    ticking.join(timeout=5)

    assert not timed_out.is_set(), "the held run waited 5 s without a release"
    assert held[HUB] is not None
    assert held[OTHER] is None
    assert not ticking.is_alive()
    assert state_of(snapshot, OTHER).check is not None


def test_rereads_without_waiting_when_doctor_run_is_held() -> None:
    """A write's ``reread()`` never waits for a doctor run in progress (the run is outside the
    writer lock), and what it read shows before the run ends."""
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub(), OTHER: an_other_hub()}, clock)
    entered, release, timed_out, hold = a_hold()
    reader.during_run[HUB] = hold
    registry = a_registry(clock, HUB)
    snapshot = HubSnapshot(registry, reader, running_version=RUNNING, clock=clock)
    ticking = threading.Thread(target=snapshot.refresh)
    ticking.start()
    assert entered.wait(timeout=5)

    registry.add(OTHER)
    rereading = threading.Thread(target=snapshot.reread)
    rereading.start()
    rereading.join(timeout=2)
    ended_while_held = not rereading.is_alive()
    listed_while_held = [state.read.entry.path for state in snapshot.hubs()]
    release.set()
    ticking.join(timeout=5)
    rereading.join(timeout=5)

    assert not timed_out.is_set(), "the held run waited 5 s without a release"
    assert ended_while_held, "reread() waited for the held doctor run"
    assert listed_while_held == [HUB, OTHER]
    assert not ticking.is_alive()


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
    entered, release, timed_out, hold = a_hold()
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

    assert not timed_out.is_set(), "the held run waited 5 s without a release"
    assert not ticking.is_alive()
    assert snapshot.hubs() == ()
    registry.add(HUB)
    snapshot.reread()
    [state] = snapshot.hubs()
    assert state.check is None


class CountingReader(FakeHubFileReader):
    """A reader that counts its ``hub.json`` and ``hub.lock`` reads."""

    def __init__(self, hubs: dict[str, FakeHub]) -> None:
        super().__init__(hubs)
        self.json_reads = 0
        self.lock_reads = 0

    def read_hub_json(self, hub_path: str) -> bytes | UnreadHubFile:
        self.json_reads += 1
        return super().read_hub_json(hub_path)

    def read_lock(self, hub_path: str) -> LockState | None:
        self.lock_reads += 1
        return super().read_lock(hub_path)


def test_reads_hub_json_again_only_when_its_time_changes() -> None:
    clock = Clock()
    reader = CountingReader({HUB: a_hub()})
    snapshot = a_snapshot(reader, clock)
    tick(snapshot, clock, 0)
    first = (reader.json_reads, reader.lock_reads)

    snapshot.hubs()
    snapshot.hubs()
    tick(snapshot, clock, 2)
    unchanged = (reader.json_reads, reader.lock_reads)
    reader.hubs[HUB].mtimes["hub.json"] = 11
    tick(snapshot, clock, 4)
    json_changed = (reader.json_reads, reader.lock_reads)
    tick(snapshot, clock, 6)
    settled = (reader.json_reads, reader.lock_reads)
    reader.hubs[HUB].mtimes["hub.lock"] = 12
    tick(snapshot, clock, 8)

    assert unchanged == first
    assert json_changed[0] == first[0] + 1
    assert settled == json_changed
    assert reader.lock_reads == settled[1] + 1
    # Only the first tick ran the doctor (the others are within 10 s of it), so every count
    # after it is a read of the hub's facts.
    assert reader.snapshots == {HUB: 1}


class LinkedReader(FakeHubFileReader):
    """A reader whose ``hub.json`` and ``hub.lock`` play links: ``mtimes`` holds each link's own
    time, ``followed`` the time of the file it points at."""

    def __init__(self, hubs: dict[str, FakeHub], *, followed: dict[str, int]) -> None:
        super().__init__(hubs)
        self.followed = followed

    def followed_times(self, hub_path: str, paths: Sequence[str]) -> tuple[int | None, ...]:
        own = self.modified_times(hub_path, paths)
        return tuple(self.followed.get(path, time) for path, time in zip(paths, own, strict=True))


@pytest.mark.parametrize(
    ("link", "changes", "expected"),
    [
        pytest.param(
            "hub.json",
            {"hub_json": hub_json_bytes(pin="9.9.9")},
            ("9.9.9", LockAbsent()),
            id="hub-json",
        ),
        pytest.param("hub.lock", {"lock": a_lock()}, (RUNNING, a_lock()), id="hub-lock"),
    ],
)
def test_reads_facts_again_when_link_points_at_other_file_with_same_time(
    *, link: str, changes: dict[str, object], expected: tuple[str, LockState]
) -> None:
    """A ``hub.json`` or ``hub.lock`` link pointed at another file with the same time (``cp -p``,
    ``tar -x``, a file system of whole seconds) keeps its followed time but gets a time of its
    own: the next tick reads that file again."""
    clock = Clock()
    reader = LinkedReader({HUB: a_hub()}, followed={"hub.json": 50, "hub.lock": 60})
    snapshot = a_snapshot(reader, clock)
    tick(snapshot, clock, 0)
    before = state_of(snapshot, HUB)
    assert (before.read.view.platform_pin, before.lock) == (RUNNING, LockAbsent())
    for name, value in changes.items():
        setattr(reader.hubs[HUB], name, value)
    reader.hubs[HUB].mtimes[link] += 10

    tick(snapshot, clock, 2)

    after = state_of(snapshot, HUB)
    assert reader.followed_times(HUB, ("hub.json", "hub.lock")) == (50, 60)
    assert (after.read.view.platform_pin, after.lock) == expected


def test_checks_hub_with_invalid_config_when_it_names_project() -> None:
    document = json.loads(hub_json_bytes(pin=RUNNING))
    document["tracker"] = "linear"
    raw = json.dumps(document).encode()
    read = read_hub_document(raw, running_version=RUNNING)
    assert (read.project, read.valid) == ("demo", False)
    reader = a_reader(hub_json=raw)
    snapshot = a_snapshot(reader, Clock())

    snapshot.refresh()

    check = state_of(snapshot, HUB).check
    assert check is not None
    assert CONFIG_SCHEMA_RULE in {finding.rule for finding in check.findings}


def test_runs_hub_at_next_tick_when_written_through_app_within_min_interval() -> None:
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub(), OTHER: an_other_hub()}, clock)
    reader.failing.add(OTHER)
    snapshot = HubSnapshot(
        a_registry(clock, HUB, OTHER), reader, running_version=RUNNING, clock=clock
    )
    tick(snapshot, clock, 0, 2)
    # OTHER failed twice, so its backoff holds it until 12 s.
    assert (reader.seconds(HUB), reader.seconds(OTHER)) == ([0], [0, 2])
    clock.now = START + timedelta(seconds=3)
    reader.hubs[HUB].mtimes["AGENTS.md"] = 4
    snapshot.reread(written=HUB)
    snapshot.reread(written=OTHER)

    tick(snapshot, clock, 4)
    marked = (reader.seconds(HUB), reader.seconds(OTHER))
    tick(snapshot, clock, 6)

    # Both run at the next tick: HUB 4 s after its last run, OTHER within its backoff.
    assert marked == ([0, 4], [0, 2, 4])
    # The mark clears when the run starts: 2 s later, with no write, HUB runs nothing.
    assert reader.seconds(HUB) == [0, 4]


@pytest.mark.parametrize(
    ("failing", "changed", "before"),
    [
        # Checked at 0 s, nothing changed: a negative age counts as past the TTL.
        pytest.param(False, False, [0], id="ttl"),
        # Checked at 0 s, a watched file changed: a negative age counts as past the spacing.
        pytest.param(False, True, [0], id="spacing"),
        # Failed at 0 and 2 s, so the backoff holds it until 12 s: a negative age ends it.
        pytest.param(True, False, [0, 2], id="backoff"),
    ],
)
def test_runs_hub_at_next_tick_when_clock_is_set_back(
    *, failing: bool, changed: bool, before: list[int]
) -> None:
    """The wall clock set back an hour makes a hub's age (now minus its last run) negative: the
    next tick runs it, and the tick 2 s after that run does not run it again."""
    clock = Clock()
    reader = ScriptedReader({HUB: a_hub()}, clock)
    if failing:
        reader.failing.add(HUB)
    snapshot = a_snapshot(reader, clock)
    tick(snapshot, clock, *before)
    assert reader.seconds(HUB) == before
    if changed:
        reader.hubs[HUB].mtimes["AGENTS.md"] = 4

    tick(snapshot, clock, -3600, -3598)

    assert reader.seconds(HUB) == [*before, -3600]
