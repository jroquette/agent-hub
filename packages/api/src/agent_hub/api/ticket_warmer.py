"""The ticket warmer of ``hub web``: Linear's ticket cache kept warm while a tab is open (AGH-613).

``TicketWarmer`` is an ``AppLifecycle`` part beside the doctor refresher. Its ticker ticks every
``WARM_SECONDS`` and at once when the first tab opens (``ConnectedBrowsers``' first-open hook
wakes it), so the Features list, which reads only what the cache holds, shows Linear's tickets
without the page asking for them.

A tick does nothing unless a tab holds the global stream open and a Linear key is set
(``key_digest()`` is not None), so with no key it lists no feature folder; nor during a pause.
``requests()`` leaves out each hub whose transport is ``mcp`` before listing its folders, so
the warmer reads what it read before ADR 0060; that hub's feature page still reads its tickets
on demand. Otherwise, for each of the first ``WARM_LIMIT`` requests, in
``requests()`` order, it reads what the cache holds (never the tracker) and fetches only an entry
that is not a good Linear snapshot (missing, the plan, or a failure, which the cache holds 60 s)
or is at least ``REFRESH_AGE`` old: one minute before the cache's 15 min stale limit, so the list
never falls back to the plan while a tab is open, and each feature is read about once per 14
min, not once per 60 s TTL. An entry's age is judged by the clock read when the tick reaches it,
not at the tick's start, so slow reads earlier in the tick do not make a later entry look
younger than it is.
``WARM_LIMIT`` leaves 32 of the cache's ``MAX_ENTRIES`` to the feature pages' own reads, so no
warmed entry is dropped before the next tick (a dropped one would be read again every tick);
how many requests a tick leaves out is logged once, as a warning, with the count only.

While ``hubs.json`` cannot be read, ``requests()`` raises ``HubRegistryError`` on every tick: the
tick takes it as nothing to warm and logs nothing, since the doctor refresher already reports
that outage once (a warning when it starts, an info line when the registry reads again), and the
first tick that reads the registry warms again. Any other error a tick raises is the ticker's to
log: one warning per tick, with the error's type only.

A rate-limit answer ends the tick and pauses the warmer for the cache's ``RATE_LIMIT_COOLDOWN``.
A refused key (``unauthorized``) ends the tick and pauses it for ``UNAUTHORIZED_PAUSE``, or until
a key other than the refused one has been seen for ``FAILURE_HOLD``: the cache holds a refusal
that long whatever the key, so a fetch right after a new key could get the old key's held
refusal. Every tick, paused or not, notes when it first sees a key other than the last one
(compared by its digest, kept in memory and never logged); a refusal within ``NEW_KEY_WINDOW``
of that (the hold plus the wait for a read in flight, ``WAIT_LIMIT_SECONDS``) starts no 15 min
pause, since it can be the old key's: the warmer only waits that window out.

``stop`` never waits for a read in progress. The warmer reads hub files and Linear only, never a
store.
"""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Final

from agent_hub.api.connected_browsers import ConnectedBrowsers
from agent_hub.api.doctor_refresher import Ticker
from agent_hub.api.ticket_snapshots import (
    FAILURE_HOLD,
    MAX_ENTRIES,
    RATE_LIMIT_COOLDOWN,
    WAIT_LIMIT_SECONDS,
)
from agent_hub.core.errors import TrackerFailure
from agent_hub.core.features.ticket_snapshots import SnapshotRead, SnapshotRequest, TicketSnapshots
from agent_hub.core.hubs.hub_registry import HubRegistryError

WARM_SECONDS: Final = 30.0
REFRESH_AGE: Final = timedelta(minutes=14)
WARM_LIMIT: Final = MAX_ENTRIES - 32
UNAUTHORIZED_PAUSE: Final = timedelta(minutes=15)
NEW_KEY_WINDOW: Final = FAILURE_HOLD + timedelta(seconds=WAIT_LIMIT_SECONDS)

_log = logging.getLogger(__name__)


class TicketWarmer:
    """The ``AppLifecycle`` part that keeps the ticket cache warm (see the module docstring)."""

    def __init__(
        self,
        requests: Callable[[], Sequence[SnapshotRequest]],
        snapshots: TicketSnapshots,
        browsers: ConnectedBrowsers,
        *,
        ticker: Ticker,
        key_digest: Callable[[], str | None],
        clock: Callable[[], datetime],
    ) -> None:
        self._requests = requests
        self._snapshots = snapshots
        self._browsers = browsers
        self._ticker = ticker
        self._key_digest = key_digest
        self._clock = clock
        # The state below is changed by the ticks only, one at a time.
        self._digest: str | None = None
        self._has_seen_key = False
        # When a tick first saw ``_digest`` in place of another one; None for the first seen.
        self._new_key_at: datetime | None = None
        self._paused_until: datetime | None = None
        # The refused key's digest while its pause runs.
        self._refused: str | None = None
        self._warned = False

    async def start(self) -> None:
        """Start the ticks; never raises."""
        self._ticker.start(self._tick)

    def begin_exit(self) -> None:
        """Stop the ticks without waiting for one in progress."""
        self._ticker.stop()

    async def stop(self) -> None:
        """Stop the ticks without waiting for a read in progress."""
        self._ticker.stop()

    def _tick(self) -> None:
        now = self._clock()
        digest = self._key_digest()
        self._note_key(digest, now)
        if digest is None or not self._browsers.connected() or self._is_paused(digest, now):
            return
        requests = self._readable_requests()
        self._warn_once(len(requests) - WARM_LIMIT)
        for request in requests[:WARM_LIMIT]:
            reached_at = self._clock()
            if _is_warm(self._snapshots.cached(request), reached_at):
                continue
            failure = self._snapshots.fetch(request).failure
            if failure in {"rate_limited", "unauthorized"}:
                self._pause(failure, digest, self._clock())
                return

    def _readable_requests(self) -> tuple[SnapshotRequest, ...]:
        """What ``requests()`` lists; nothing while the hub registry cannot be read."""
        try:
            return tuple(self._requests())
        except HubRegistryError:
            # No line: the doctor refresher logs the outage once, not once per tick.
            return ()

    def _note_key(self, digest: str | None, now: datetime) -> None:
        """Note when a tick first sees a key other than the last one."""
        if self._has_seen_key and digest != self._digest:
            self._new_key_at = now
        self._digest, self._has_seen_key = digest, True

    def _is_paused(self, digest: str, now: datetime) -> bool:
        """Whether a pause runs now; one that has ended is forgotten."""
        if self._paused_until is None:
            return False
        if now < self._paused_until and not self._new_key_ends_refusal(digest, now):
            return True
        self._paused_until = self._refused = None
        return False

    def _new_key_ends_refusal(self, digest: str, now: datetime) -> bool:
        """Whether a key other than the refused one has been seen for ``FAILURE_HOLD``."""
        return (
            self._refused is not None
            and digest != self._refused
            and self._new_key_at is not None
            and now - self._new_key_at >= FAILURE_HOLD
        )

    def _pause(self, failure: TrackerFailure, digest: str, now: datetime) -> None:
        """Pause after a rate-limit answer or a refused key answered at ``now``."""
        self._refused = None
        if failure == "rate_limited":
            self._paused_until = now + RATE_LIMIT_COOLDOWN
        elif self._new_key_at is not None and now - self._new_key_at < NEW_KEY_WINDOW:
            # The refusal can be the old key's (held, or read just before the change).
            self._paused_until = self._new_key_at + NEW_KEY_WINDOW
        else:
            self._paused_until, self._refused = now + UNAUTHORIZED_PAUSE, digest

    def _warn_once(self, left_out: int) -> None:
        """Log once how many requests the ticks leave out over ``WARM_LIMIT``."""
        if left_out > 0 and not self._warned:
            self._warned = True
            _log.warning("ticket warmer leaves %d features out of each tick", left_out)


def _is_warm(read: SnapshotRead, now: datetime) -> bool:
    """Whether the cache holds a good Linear snapshot younger than ``REFRESH_AGE``."""
    return (
        read.source == "linear"
        and read.failure is None
        and read.as_of is not None
        and now - read.as_of < REFRESH_AGE
    )
