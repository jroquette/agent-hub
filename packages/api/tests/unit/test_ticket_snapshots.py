import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

import pytest

from agent_hub.api.ticket_snapshots import (
    FAILURE_HOLD,
    MAX_ENTRIES,
    RATE_LIMIT_COOLDOWN,
    TTL,
    WAIT_LIMIT_SECONDS,
    CachedTicketSnapshots,
)
from agent_hub.core.errors import TrackerFailure
from agent_hub.core.features.ticket_snapshots import SnapshotRead, SnapshotRequest
from agent_hub.core.testing.tracker_reader_fakes import (
    SNAPSHOT_TIME,
    CountingTrackerReader,
    FailingTrackerReader,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)
from agent_hub.core.tracker.tracker_reader import TicketSnapshot, TrackerReader

REQUEST = SnapshotRequest.of(project="demo", transport="api", ids=("DEM-2", "DEM-1"))


class FakeClock:
    def __init__(self) -> None:
        self.now = SNAPSHOT_TIME

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class SwitchableReaders:
    """``reader_of`` whose reader a test swaps; None is "not connected"."""

    def __init__(self, reader: TrackerReader | None) -> None:
        self.reader = reader

    def __call__(self, request: SnapshotRequest) -> TrackerReader | None:
        return self.reader


def a_counting_reader(before: Callable[[], object] | None = None) -> CountingTrackerReader:
    return CountingTrackerReader(InMemoryTrackerReader(a_seeded_issue_board()), before=before)


def cache_over(
    reader: TrackerReader | None, *, wait_limit_seconds: float = WAIT_LIMIT_SECONDS
) -> tuple[CachedTicketSnapshots, SwitchableReaders, FakeClock]:
    readers, clock = SwitchableReaders(reader), FakeClock()
    cache = CachedTicketSnapshots(readers, clock=clock, wait_limit_seconds=wait_limit_seconds)
    return cache, readers, clock


def wait_until(condition: Callable[[], bool], *, timeout: float = 10) -> bool:
    """Poll ``condition`` (a structural check, not a timing one) until true or ``timeout``."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.001)
    return True


class Gate:
    """A ``before`` hook that parks the reader until ``release``; ``started`` once inside."""

    def __init__(self) -> None:
        self.started, self.released = threading.Event(), threading.Event()

    def __call__(self) -> None:
        self.started.set()
        self.released.wait(timeout=10)

    def release(self) -> None:
        self.released.set()


def ids_of(read: SnapshotRead) -> tuple[str, ...]:
    assert read.snapshot is not None
    return tuple(summary.id for summary in read.snapshot.summaries)


def test_calls_reader_once_when_read_twice_within_ttl() -> None:
    reader = a_counting_reader()
    cache, _, clock = cache_over(reader)

    first = cache.fetch(REQUEST)
    clock.advance(59)
    second = cache.fetch(REQUEST)

    assert reader.count == 1
    assert ids_of(first) == ids_of(second) == ("DEM-1", "DEM-2")
    assert (second.source, second.stale, second.as_of, second.failure) == (
        "linear",
        False,
        SNAPSHOT_TIME,
        None,
    )


def test_calls_reader_again_when_cache_read_after_ttl() -> None:
    reader = a_counting_reader()
    cache, _, clock = cache_over(reader)
    cache.fetch(REQUEST)

    clock.advance(61)
    read = cache.fetch(REQUEST)

    assert reader.count == 2
    assert read.as_of == SNAPSHOT_TIME + timedelta(seconds=61)


def test_calls_reader_once_when_eight_threads_read_cold() -> None:
    gate = Gate()
    reader = a_counting_reader(before=gate)
    cache, _, _ = cache_over(reader)
    reads: list[SnapshotRead] = []
    threads = [
        threading.Thread(target=lambda: reads.append(cache.fetch(REQUEST))) for _ in range(8)
    ]

    for thread in threads:
        thread.start()
    parked = gate.started.wait(timeout=10) and wait_until(lambda: cache.waiting == 7)
    gate.release()
    for thread in threads:
        thread.join(timeout=10)

    assert parked
    assert reader.count == 1
    assert len(reads) == 8
    assert {read.source for read in reads} == {"linear"}


def test_calls_reader_per_feature_when_cache_keyed_by_ids() -> None:
    reader = a_counting_reader()
    cache, _, _ = cache_over(reader)
    other = SnapshotRequest.of(project="demo", transport="api", ids=("DEM-3",))

    cache.fetch(REQUEST)
    cache.fetch(other)
    cache.fetch(SnapshotRequest.of(project="demo", transport="api", ids=("DEM-1", "DEM-2")))

    assert reader.calls == [("DEM-1", "DEM-2"), ("DEM-3",)]


def test_drops_least_recently_used_when_cache_over_bound() -> None:
    reader = a_counting_reader()
    cache, _, _ = cache_over(reader)
    requests = [
        SnapshotRequest.of(project=f"p{index}", transport="api", ids=("DEM-1",))
        for index in range(MAX_ENTRIES)
    ]
    for request in requests:
        cache.fetch(request)

    cache.fetch(requests[0])
    cache.fetch(SnapshotRequest.of(project="one-more", transport="api", ids=("DEM-1",)))
    kept, dropped = cache.cached(requests[0]), cache.cached(requests[1])

    assert reader.count == MAX_ENTRIES + 1
    assert (kept.source, dropped.source, dropped.failure) == ("linear", "plan", None)


def test_never_calls_reader_when_cached_read() -> None:
    reader = a_counting_reader()
    cache, _, _ = cache_over(reader)

    cold = cache.cached(REQUEST)
    cache.fetch(REQUEST)
    warm = cache.cached(REQUEST)

    assert reader.count == 1
    assert (cold.source, cold.snapshot, cold.failure, cold.as_of) == ("plan", None, None, None)
    assert (warm.source, warm.stale, warm.as_of) == ("linear", False, SNAPSHOT_TIME)


def test_marks_cached_stale_when_older_than_ttl() -> None:
    cache, _, clock = cache_over(a_counting_reader())
    cache.fetch(REQUEST)

    clock.advance(61)
    read = cache.cached(REQUEST)

    assert (read.source, read.stale, read.as_of) == ("linear", True, SNAPSHOT_TIME)


def test_answers_not_connected_when_no_reader() -> None:
    cache, _, _ = cache_over(None)

    fetched, cached = cache.fetch(REQUEST), cache.cached(REQUEST)

    for read in (fetched, cached):
        assert (read.source, read.snapshot, read.failure, read.http_status) == (
            "plan",
            None,
            "not_connected",
            None,
        )


def test_falls_back_to_plan_when_cold_read_fails() -> None:
    reader = FailingTrackerReader("unavailable", http_status=500)
    cache, _, _ = cache_over(reader)

    read = cache.fetch(REQUEST)
    cached = cache.cached(REQUEST)

    for served in (read, cached):
        assert (served.source, served.snapshot, served.stale) == ("plan", None, False)
        assert (served.failure, served.http_status) == ("unavailable", 500)
        assert served.detail == "synthetic unavailable failure"
    assert reader.count == 1


def test_serves_stale_when_reader_fails_after_success() -> None:
    cache, readers, clock = cache_over(a_counting_reader())
    cache.fetch(REQUEST)
    readers.reader = FailingTrackerReader("timeout")

    clock.advance(14 * 60)
    read = cache.fetch(REQUEST)

    assert ids_of(read) == ("DEM-1", "DEM-2")
    assert (read.source, read.stale, read.as_of) == ("linear", True, SNAPSHOT_TIME)
    assert (read.failure, read.detail) == ("timeout", "synthetic timeout failure")
    assert cache.cached(REQUEST) == read


def test_falls_back_to_plan_when_stale_over_fifteen_minutes() -> None:
    cache, readers, clock = cache_over(a_counting_reader())
    cache.fetch(REQUEST)
    readers.reader = FailingTrackerReader("unauthorized", http_status=401)

    clock.advance(15 * 60 + 1)
    read = cache.fetch(REQUEST)

    assert (read.source, read.snapshot, read.stale, read.as_of) == ("plan", None, False, None)
    assert (read.failure, read.http_status) == ("unauthorized", 401)


def test_recovers_when_reader_succeeds_after_failure_hold() -> None:
    cache, readers, clock = cache_over(FailingTrackerReader("unreachable"))
    cache.fetch(REQUEST)
    readers.reader = a_counting_reader()

    clock.advance(FAILURE_HOLD.total_seconds())
    read = cache.fetch(REQUEST)

    assert (read.source, read.stale, read.failure, read.detail) == ("linear", False, None, None)


FAILURES: list[tuple[TrackerFailure, int | None]] = [
    ("unauthorized", 401),
    ("unauthorized", 403),
    ("rate_limited", 429),
    ("unavailable", 503),
    ("timeout", None),
    ("unreachable", None),
    ("unexpected", 200),
    ("other", None),
]


@pytest.mark.parametrize(("kind", "status"), FAILURES)
def test_holds_key_for_ttl_when_cache_read_fails(kind: TrackerFailure, status: int | None) -> None:
    failing = FailingTrackerReader(kind, http_status=status)
    cache, readers, clock = cache_over(failing)

    first = cache.fetch(REQUEST)
    clock.advance(TTL.total_seconds() - 1)
    readers.reader = recovered = a_counting_reader()
    during = cache.fetch(REQUEST)
    clock.advance(1)
    after = cache.fetch(REQUEST)

    assert failing.count == 1
    assert recovered.count == 1
    for read in (first, during):
        assert (read.source, read.failure, read.http_status) == ("plan", kind, status)
    assert (after.source, after.failure) == ("linear", None)
    assert FAILURE_HOLD == TTL == timedelta(seconds=60)
    assert max(FAILURE_HOLD, RATE_LIMIT_COOLDOWN) == timedelta(seconds=60)


def test_serves_stale_during_hold_when_cache_read_fails_after_ttl() -> None:
    cache, readers, clock = cache_over(a_counting_reader())
    cache.fetch(REQUEST)
    clock.advance(61)
    readers.reader = failing = FailingTrackerReader("timeout")

    first = cache.fetch(REQUEST)
    clock.advance(59)
    during = cache.fetch(REQUEST)

    assert failing.count == 1
    for read in (first, during):
        assert (read.source, read.stale, read.as_of, read.failure) == (
            "linear",
            True,
            SNAPSHOT_TIME,
            "timeout",
        )


def test_reads_at_once_when_cache_was_not_connected() -> None:
    cache, readers, _ = cache_over(None)
    cache.fetch(REQUEST)
    readers.reader = says_not_connected = FailingTrackerReader("not_connected")
    cache.fetch(REQUEST)

    readers.reader = reader = a_counting_reader()
    read = cache.fetch(REQUEST)

    assert says_not_connected.count == 1
    assert reader.count == 1
    assert (read.source, read.failure) == ("linear", None)


class ExplodingReader:
    """A reader whose first read raises an error that is not a ``TrackerError``."""

    def __init__(self) -> None:
        self.count = 0

    def issue_summaries(self, ids: Sequence[str]) -> TicketSnapshot:
        self.count += 1
        if self.count == 1:
            raise RuntimeError("synthetic bug")
        return InMemoryTrackerReader(a_seeded_issue_board()).issue_summaries(ids)


def test_reads_again_when_cache_reader_raised_other_error() -> None:
    reader = ExplodingReader()
    cache, _, _ = cache_over(reader)

    with pytest.raises(RuntimeError):
        cache.fetch(REQUEST)
    read = cache.fetch(REQUEST)

    assert reader.count == 2
    assert (read.source, read.failure) == ("linear", None)
    assert cache.waiting == 0


def test_gives_up_waiting_when_cache_read_in_flight_over_wait_limit() -> None:
    gate = Gate()
    reader = a_counting_reader(before=gate)
    cache, _, _ = cache_over(reader, wait_limit_seconds=0.01)
    holder = threading.Thread(target=lambda: cache.fetch(REQUEST))
    holder.start()
    assert gate.started.wait(timeout=10)

    waited = cache.fetch(REQUEST)
    gate.release()
    holder.join(timeout=10)

    assert reader.count == 1
    assert (waited.source, waited.snapshot, waited.failure) == ("plan", None, None)
    assert cache.waiting == 0
    assert WAIT_LIMIT_SECONDS == 30.0


def test_keeps_in_flight_entry_when_cache_over_bound() -> None:
    gate = Gate()
    held = SnapshotRequest.of(project="held", transport="api", ids=("DEM-1",))
    slow, fast = a_counting_reader(before=gate), a_counting_reader()

    def reader_of(request: SnapshotRequest) -> TrackerReader:
        return slow if request == held else fast

    cache = CachedTicketSnapshots(reader_of, clock=FakeClock())
    holder = threading.Thread(target=lambda: cache.fetch(held))
    holder.start()
    assert gate.started.wait(timeout=10)

    for index in range(MAX_ENTRIES + 1):
        cache.fetch(SnapshotRequest.of(project=f"p{index}", transport="api", ids=("DEM-1",)))
    gate.release()
    holder.join(timeout=10)
    kept = cache.cached(held)
    again = cache.fetch(held)

    assert (kept.source, again.source) == ("linear", "linear")
    assert slow.count == 1


def test_waits_cooldown_when_rate_limited() -> None:
    limited = FailingTrackerReader("rate_limited", http_status=429)
    cache, readers, clock = cache_over(a_counting_reader())
    cache.fetch(REQUEST)
    clock.advance(61)
    readers.reader = limited

    first = cache.fetch(REQUEST)
    clock.advance(59)
    during = cache.fetch(REQUEST)
    clock.advance(1)
    readers.reader = a_counting_reader()
    after = cache.fetch(REQUEST)

    assert limited.count == 1
    for read in (first, during):
        assert (read.source, read.stale, read.failure, read.http_status) == (
            "linear",
            True,
            "rate_limited",
            429,
        )
    assert (after.source, after.stale, after.failure) == ("linear", False, None)


def test_serves_plan_during_cooldown_when_rate_limited_cold() -> None:
    limited = FailingTrackerReader("rate_limited", http_status=429)
    cache, _, clock = cache_over(limited)

    cache.fetch(REQUEST)
    clock.advance(30)
    read = cache.fetch(REQUEST)

    assert limited.count == 1
    assert (read.source, read.failure, read.http_status) == ("plan", "rate_limited", 429)
