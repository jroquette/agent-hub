"""The background part of ``hub web`` that keeps each hub's facts and last check fresh (AGH-608).

``DoctorRefresher`` is an ``AppLifecycle`` part over the hub read models: ``start`` reads the
registry and every hub's ``hub.json`` and ``hub.lock`` once (``reread_hubs``), so the first
request already lists every hub, with null health until its first check, and then starts its
ticker. Each tick is one ``refresh()`` of the hub snapshot: the facts that changed, then the
doctor of each due hub (``agent_hub.core.hubs.hub_snapshot`` says when a hub is due). No request
ever runs the doctor.

``DaemonTicker`` ticks at once, then every ``interval`` after the previous tick ends, on a daemon
thread of its own: never ``asyncio.to_thread``, whose executor uvicorn waits for when it closes,
so a doctor run in progress would hold the exit. ``stop()`` sets a flag and ends the wait at
once; it never joins the thread, and a run in progress finishes on its own (it reads hub files
only, never a store). A tick that raises is logged with the error's type and the next one runs.

Logs never quote a failure's message or traceback, which can hold file text: a failed run is
one warning with the hub path and the error's type; ``hub doctor`` in that hub shows the whole
error. ``start`` never raises: a registry it cannot read is logged with its type, the routes
answer 503 until a tick reads it.
"""

import logging
import threading
from collections.abc import Callable
from typing import Final, Protocol

from agent_hub.core.hubs.hub_snapshot import RefreshReport

POLL_SECONDS: Final = 2.0

_log = logging.getLogger(__name__)


def _no_tick() -> None:
    """The tick of a ticker not started yet: nothing."""


class Ticker(Protocol):
    """What runs a tick again and again until it is stopped."""

    def start(self, tick: Callable[[], None]) -> None:
        """Run ``tick`` now and then again and again, off the caller's thread."""
        ...

    def stop(self) -> None:
        """Run no further tick; returns at once, without waiting for one in progress."""
        ...


class DaemonTicker:
    """A ``Ticker`` on a daemon thread named ``name`` (see the module docstring)."""

    def __init__(self, interval: float, *, name: str) -> None:
        self._interval = interval
        self._name = name
        self._stopped = threading.Event()
        self._tick: Callable[[], None] = _no_tick
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    @property
    def thread(self) -> threading.Thread:
        """The thread the ticks run on (a test joins it)."""
        return self._thread

    def start(self, tick: Callable[[], None]) -> None:
        """Start the thread: ``tick`` at once, then every ``interval`` after each one ends."""
        self._tick = tick
        self._thread.start()

    def stop(self) -> None:
        """Run no further tick and end the wait for the next one; never waits for a tick."""
        self._stopped.set()

    def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                self._tick()
            except Exception as error:  # noqa: BLE001 -- one failed tick never stops the next
                _log.warning(
                    "background tick failed: %s",
                    self._name,
                    extra={"error_type": type(error).__name__},
                )
            if self._stopped.wait(self._interval):
                return


class RefreshedHubs(Protocol):
    """The hub reads the refresher keeps fresh (``HubFilesReadModels``)."""

    def reread_hubs(self, written: str | None = None) -> None:
        """Read the registry and every hub's ``hub.json`` and ``hub.lock`` now."""
        ...

    def refresh(self) -> RefreshReport:
        """One tick of the hub snapshot."""
        ...


class DoctorRefresher:
    """The ``AppLifecycle`` part that rereads the hubs at start and ticks their snapshot."""

    def __init__(self, hubs: RefreshedHubs, *, ticker: Ticker) -> None:
        self._hubs = hubs
        self._ticker = ticker

    async def start(self) -> None:
        """Read every hub once, then start the ticks; never raises (review finding 5: the app's
        lifespan starts its parts with no rollback, so a raising part would leave the others
        running)."""
        try:
            self._hubs.reread_hubs()
        except Exception as error:  # noqa: BLE001 -- logged; the first tick reads again
            _log.warning(
                "hub registry read failed at start", extra={"error_type": type(error).__name__}
            )
        self._ticker.start(self._tick)

    def begin_exit(self) -> None:
        """Stop the ticks without waiting for one in progress."""
        self._ticker.stop()

    async def stop(self) -> None:
        """Stop the ticks without waiting for one in progress (it reads hub files only)."""
        self._ticker.stop()

    def _tick(self) -> None:
        report = self._hubs.refresh()
        for failure in report.failures:
            _log.warning(
                "background doctor run failed: %s",
                failure.hub_path,
                extra={"error_type": type(failure.error).__name__},
            )
