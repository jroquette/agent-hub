"""What ``hub web`` runs for the scheduled and event starts while it serves (ADR 0048).

``ScheduledStartsRuntime`` is an ``AppLifecycle``: ``start`` creates one task that ticks at once
(so a slot missed while ``hub web`` was down runs on start, and the first poll records the event
sources' baseline), then every ``tick_seconds``. A tick runs ``start_due_slots`` with the clock's
time and, when ``poll_seconds`` have passed since the last poll, ``poll_events``, each in a
thread (they read files and run ``gh``). Each start is logged at info, each failure as a
warning; a tick that raises is logged and the next one runs (as the agent sessions' sweep).
One tick at a time: a tick that overruns delays the next. ``begin_exit`` (the server's signal
hook) cancels the task through the loop; ``stop`` waits for it.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Final, Protocol

from agent_hub.core.schedules.scheduled_starts import StartReport

TICK_SECONDS: Final = 60.0
POLL_SECONDS: Final = 300.0

_log = logging.getLogger(__name__)


class ScheduledStarts(Protocol):
    """``StartScheduledRuns``'s two steps."""

    def start_due_slots(self, now: datetime) -> StartReport:
        """Start the due slots."""
        ...

    def poll_events(self) -> StartReport:
        """Poll the event sources and start the new events."""
        ...


class ScheduledStartsRuntime:
    """The scheduled starts' lifecycle in ``hub web`` (see the module docstring)."""

    def __init__(
        self,
        starts: ScheduledStarts,
        *,
        clock: Callable[[], datetime],
        tick_seconds: float = TICK_SECONDS,
        poll_seconds: float = POLL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._starts = starts
        self._clock = clock
        self._tick_seconds = tick_seconds
        self._poll_seconds = poll_seconds
        self._monotonic = monotonic
        self._polled_at: float | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start ticking: once now, then every ``tick_seconds``."""
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._tick_forever())

    def begin_exit(self) -> None:
        """Cancel the ticks on the loop; safe from a signal handler or another thread."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._cancel)

    async def stop(self) -> None:
        """Cancel the ticks and wait until the task has ended."""
        self._cancel()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def tick(self) -> None:
        """Start the due slots, and poll the events when it is time."""
        _log_report(await asyncio.to_thread(self._starts.start_due_slots, self._clock()))
        now = self._monotonic()
        if self._polled_at is None or now - self._polled_at >= self._poll_seconds:
            self._polled_at = now
            _log_report(await asyncio.to_thread(self._starts.poll_events))

    def _cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _tick_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 -- one failed tick never stops the next
                _log.warning("scheduled starts tick failed", exc_info=True)
            await asyncio.sleep(self._tick_seconds)


def _log_report(report: StartReport) -> None:
    for run in report.started:
        _log.info(
            "scheduled run started: %s %s %s (%s)",
            run.project,
            run.workflow,
            run.run_id,
            run.trigger,
        )
    for failure in report.failures:
        _log.warning(
            "scheduled start failed: %s %s: %s",
            failure.project,
            failure.workflow or "-",
            failure.reason,
            # An unexpected error's traceback stays in the local log, never in the reason.
            exc_info=failure.error,
        )
