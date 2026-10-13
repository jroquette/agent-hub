"""``CachedTicketSnapshots``: the in-memory ``TicketSnapshots`` cache of ``hub web`` (AGH-136 S2).

One entry per ``SnapshotRequest`` (the project and a feature's sorted ids, E8), at most
``MAX_ENTRIES``, the least recently used dropped first. ``fetch`` reads the tracker only when
the entry holds no snapshot younger than ``TTL`` and no 429 cool-down runs (E3); concurrent
fetches of one key share a single read (single flight) and the others get its result. After a
failure the last good snapshot is served as ``stale`` while it is at most ``STALE_LIMIT`` old,
else the plan, both with the failure. ``cached`` never reads the tracker (Q6).

The reader comes from ``reader_of`` on every call (None: not connected, no key or the MCP
transport), so a key set while ``hub web`` runs takes effect at once. ``REQUEST_TIMEOUT_SECONDS``
and ``READ_BUDGET_SECONDS`` are the bounds the composition gives the reader (Q5).
"""

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from agent_hub.core.errors import TrackerError, TrackerFailure
from agent_hub.core.features.ticket_snapshots import SnapshotRead, SnapshotRequest
from agent_hub.core.tracker.tracker_reader import TicketSnapshot, TrackerReader

TTL: Final = timedelta(seconds=60)
STALE_LIMIT: Final = timedelta(minutes=15)
RATE_LIMIT_COOLDOWN: Final = timedelta(seconds=60)
MAX_ENTRIES: Final = 256
REQUEST_TIMEOUT_SECONDS: Final = 10.0
READ_BUDGET_SECONDS: Final = 20.0
# A read checks its budget between pages, so it may overrun it by one request.
_WAIT_LIMIT_SECONDS: Final = READ_BUDGET_SECONDS + REQUEST_TIMEOUT_SECONDS
NOT_CONNECTED_DETAIL: Final = "Linear is not connected for hub web"

type ReaderOf = Callable[[SnapshotRequest], TrackerReader | None]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _Failure:
    kind: TrackerFailure
    detail: str
    http_status: int | None


@dataclass(slots=True)
class _Entry:
    snapshot: TicketSnapshot | None = None
    read_at: datetime | None = None
    failure: _Failure | None = None
    cooldown_until: datetime | None = None
    reading: bool = False


class CachedTicketSnapshots:
    """A thread-safe ``TicketSnapshots`` over the reader ``reader_of`` gives, timed by ``clock``."""

    def __init__(self, reader_of: ReaderOf, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._reader_of = reader_of
        self._clock = clock
        self._condition = threading.Condition()
        self._entries: OrderedDict[SnapshotRequest, _Entry] = OrderedDict()

    def fetch(self, request: SnapshotRequest) -> SnapshotRead:
        """The fresh snapshot, read from the tracker unless cached, in a cool-down or in flight."""
        reader = self._reader_of(request)
        if reader is None:
            return _not_connected()
        with self._condition:
            entry = self._touch(request)
            if entry.reading:
                self._condition.wait_for(lambda: not entry.reading, timeout=_WAIT_LIMIT_SECONDS)
                return self._view(entry)
            now = self._clock()
            if _is_fresh(entry, now) or _cooling(entry, now):
                return self._view(entry)
            entry.reading = True
        try:
            snapshot = reader.issue_summaries(request.ids)
        except TrackerError as error:
            return self._finish(entry, failure=error)
        except BaseException:
            self._finish(entry)
            raise
        return self._finish(entry, snapshot=snapshot)

    def cached(self, request: SnapshotRequest) -> SnapshotRead:
        """What the cache holds for ``request``: never reads the tracker."""
        if self._reader_of(request) is None:
            return _not_connected()
        with self._condition:
            entry = self._entries.get(request)
            if entry is None:
                return _plan(None)
            self._entries.move_to_end(request)
            return self._view(entry)

    def _touch(self, request: SnapshotRequest) -> _Entry:
        """The request's entry, made most recently used; a new one may drop the least recent."""
        entry = self._entries.get(request)
        if entry is not None:
            self._entries.move_to_end(request)
            return entry
        entry = self._entries[request] = _Entry()
        idle = [
            key for key, kept in self._entries.items() if not kept.reading and kept is not entry
        ]
        for key in idle[: max(0, len(self._entries) - MAX_ENTRIES)]:
            del self._entries[key]
        return entry

    def _finish(
        self,
        entry: _Entry,
        *,
        snapshot: TicketSnapshot | None = None,
        failure: TrackerError | None = None,
    ) -> SnapshotRead:
        """Record the read's outcome, wake the readers waiting on it and serve the entry."""
        with self._condition:
            now = self._clock()
            if snapshot is not None:
                entry.snapshot, entry.read_at = snapshot, now
                entry.failure = entry.cooldown_until = None
            elif failure is not None:
                entry.failure = _Failure(failure.kind, failure.cause, failure.http_status)
                if failure.kind == "rate_limited":
                    entry.cooldown_until = now + RATE_LIMIT_COOLDOWN
            entry.reading = False
            self._condition.notify_all()
            return self._view(entry)

    def _view(self, entry: _Entry) -> SnapshotRead:
        """The entry served now: its snapshot while at most ``STALE_LIMIT`` old, else the plan."""
        if entry.snapshot is None or entry.read_at is None:
            return _plan(entry.failure)
        age = self._clock() - entry.read_at
        if age > STALE_LIMIT:
            return _plan(entry.failure)
        failure = entry.failure
        return SnapshotRead(
            snapshot=entry.snapshot,
            source="linear",
            stale=failure is not None or age >= TTL,
            as_of=entry.read_at,
            failure=None if failure is None else failure.kind,
            detail=None if failure is None else failure.detail,
            http_status=None if failure is None else failure.http_status,
        )


def _is_fresh(entry: _Entry, now: datetime) -> bool:
    return entry.read_at is not None and entry.failure is None and now - entry.read_at < TTL


def _cooling(entry: _Entry, now: datetime) -> bool:
    return entry.cooldown_until is not None and now < entry.cooldown_until


def _plan(failure: _Failure | None) -> SnapshotRead:
    return SnapshotRead(
        snapshot=None,
        source="plan",
        stale=False,
        as_of=None,
        failure=None if failure is None else failure.kind,
        detail=None if failure is None else failure.detail,
        http_status=None if failure is None else failure.http_status,
    )


def _not_connected() -> SnapshotRead:
    return _plan(_Failure("not_connected", NOT_CONNECTED_DETAIL, None))
