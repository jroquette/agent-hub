import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from agent_hub.api.ticket_snapshots import MAX_ENTRIES, CachedTicketSnapshots
from agent_hub.core.features.ticket_snapshots import SnapshotRead, SnapshotRequest
from agent_hub.core.testing.tracker_reader_fakes import (
    SNAPSHOT_TIME,
    CountingTrackerReader,
    FailingTrackerReader,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)
from agent_hub.core.tracker.tracker_reader import TrackerReader

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
    reader: TrackerReader | None,
) -> tuple[CachedTicketSnapshots, SwitchableReaders, FakeClock]:
    readers, clock = SwitchableReaders(reader), FakeClock()
    return CachedTicketSnapshots(readers, clock=clock), readers, clock


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
    started, release = threading.Event(), threading.Event()

    def hold() -> None:
        started.set()
        release.wait(timeout=10)

    reader = a_counting_reader(before=hold)
    cache, _, _ = cache_over(reader)
    reads: list[SnapshotRead] = []
    threads = [
        threading.Thread(target=lambda: reads.append(cache.fetch(REQUEST))) for _ in range(8)
    ]

    for thread in threads:
        thread.start()
    assert started.wait(timeout=10)
    release.set()
    for thread in threads:
        thread.join(timeout=10)

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


def test_recovers_when_reader_succeeds_after_failure() -> None:
    cache, readers, clock = cache_over(FailingTrackerReader("unreachable"))
    cache.fetch(REQUEST)
    readers.reader = a_counting_reader()

    clock.advance(1)
    read = cache.fetch(REQUEST)

    assert (read.source, read.stale, read.failure, read.detail) == ("linear", False, None, None)


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
