"""The change feed: polls the store's high-water mark so every stream learns of new events.

Appends from other processes (``hub collect``, ``hub run``) never pass through this server, so
streams cannot be woken by the append itself; they wait on the mark instead (spec "SSE"). The
mark is read at most once per interval, however many streams wait.
"""

import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from starlette.concurrency import run_in_threadpool

from agent_hub.core.events.event_reader import EventReader

POLL_INTERVAL_SECONDS = 0.5


class StreamTimer(Protocol):
    """The time sources of the streams; tests pass a fake whose ``sleep`` moves its clock."""

    def now(self) -> datetime:
        """The current time, aware and in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds on a clock that never goes back."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Wait ``seconds``."""
        ...


class SystemTimer:
    """The real clocks; ``now`` comes from the settings' clock."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    def now(self) -> datetime:
        """The settings' clock."""
        return self._clock()

    def monotonic(self) -> float:
        """``time.monotonic``."""
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        """``asyncio.sleep``."""
        await asyncio.sleep(seconds)


class ChangeFeed:
    """Wakes waiting streams when the store's high-water mark moves past what they have seen."""

    def __init__(
        self,
        reader: EventReader,
        *,
        timer: StreamTimer,
        interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self.timer = timer
        self._reader = reader
        self._interval = interval
        self._mark = 0
        self._polled_at: float | None = None
        self._polling = asyncio.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """Whether ``close`` was called: every stream then ends."""
        return self._closed

    def close(self) -> None:
        """End every stream at its next wake-up (server shutdown)."""
        self._closed = True

    async def wait_beyond(self, seen: int, *, deadline: float) -> int | None:
        """The mark once it passes ``seen``, or the mark at ``deadline`` (monotonic seconds).

        None when the feed is closed.
        """
        while not self._closed:
            mark = await self._current_mark()
            remaining = deadline - self.timer.monotonic()
            if mark > seen or remaining <= 0:
                return mark
            await self.timer.sleep(min(self._interval, remaining))
        return None

    async def _current_mark(self) -> int:
        # One stream reads while the others wait for its answer instead of reading too.
        async with self._polling:
            now = self.timer.monotonic()
            if self._polled_at is None or now - self._polled_at >= self._interval:
                self._mark = await run_in_threadpool(self._reader.high_water_mark)
                self._polled_at = now
            return self._mark
