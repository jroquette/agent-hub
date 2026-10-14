"""What ``hub web`` runs around the agent-session use case for as long as it serves (P9, P12).

``SessionRuntime`` is the app's lifecycle for the sessions: at start it ends the rows a crash
left unfinished (``ended``/``server_stopped``) and starts the sweep task, which applies time
every ``SWEEP_SECONDS`` (permission deadlines, idle timeouts) and purges the sessions past their
retention at start and then every ``PURGE_SECONDS``. ``begin_exit`` is the server's signal hook
(``server.serve_on``): called from the signal handler, before uvicorn's graceful wait, it starts
``shutdown`` on the loop, so the live sessions end and their streams close at once. ``stop`` (the
lifespan's exit) starts it if no signal did, and waits for it: no ``claude`` is left behind.

``UnavailableSessionDriver`` and ``UnavailableCloudLauncher`` stand in for the Claude adapters
when the ``sessions`` extra is not installed (P2): the capabilities say why, and starting a
session raises ``SessionsUnavailableError`` (503).
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Final, Protocol

from agent_hub.core.agent_sessions.agent_session import EndReason
from agent_hub.core.agent_sessions.cloud import CloudReply
from agent_hub.core.agent_sessions.driver import (
    DriverAnswer,
    DriverCapabilities,
    DriverEvent,
    DriverHandle,
    PastSession,
    PermissionMode,
    StartSpec,
)
from agent_hub.core.agent_sessions.errors import SessionsUnavailableError

SWEEP_SECONDS: Final = 0.5
PURGE_SECONDS: Final = 3600.0
INSTALL_EXTRA: Final = "Install agent-hub[sessions] to drive sessions"

_log = logging.getLogger(__name__)


class UnavailableSessionDriver:
    """A ``SessionDriver`` that can start nothing, for ``reason`` (see the module docstring)."""

    def __init__(self, reason: str = INSTALL_EXTRA) -> None:
        self._reason = reason

    def _refuse(self) -> SessionsUnavailableError:
        return SessionsUnavailableError(self._reason)

    async def start(self, spec: StartSpec) -> DriverHandle:  # noqa: ARG002 -- the port's signature
        """Never starts: ``SessionsUnavailableError``."""
        raise self._refuse()

    async def send(self, handle: DriverHandle, text: str) -> None:  # noqa: ARG002 -- same
        """No session exists to send to."""
        raise self._refuse()

    async def interrupt(self, handle: DriverHandle) -> None:  # noqa: ARG002 -- same
        """No session exists to interrupt."""
        raise self._refuse()

    async def answer_permission(
        self,
        handle: DriverHandle,  # noqa: ARG002 -- same
        request_id: str,  # noqa: ARG002 -- same
        answer: DriverAnswer,  # noqa: ARG002 -- same
    ) -> None:
        """No session exists to answer."""
        raise self._refuse()

    async def set_mode(self, handle: DriverHandle, mode: PermissionMode) -> None:  # noqa: ARG002 -- same
        """No session exists to change."""
        raise self._refuse()

    async def set_model(self, handle: DriverHandle, model: str | None) -> None:  # noqa: ARG002 -- same
        """No session exists to change."""
        raise self._refuse()

    async def close(self, handle: DriverHandle) -> None:  # noqa: ARG002 -- same
        """Nothing to close."""

    async def events(self, handle: DriverHandle) -> AsyncIterator[DriverEvent]:  # noqa: ARG002 -- same
        """No session has events."""
        raise self._refuse()
        yield  # pragma: no cover -- makes this an async generator

    async def list_resumable(self, cwd: str) -> tuple[PastSession, ...]:  # noqa: ARG002 -- same
        """Nothing can be resumed without the driver."""
        return ()

    async def capabilities(self) -> DriverCapabilities:
        """Unavailable, and why."""
        return DriverCapabilities(available=False, reason=self._reason)


class UnavailableCloudLauncher:
    """A ``CloudLauncher`` that runs nothing, for ``reason`` (the ``sessions`` extra is not
    installed); ``CloudSessions`` never reaches it while the capabilities say unavailable."""

    def __init__(self, reason: str = INSTALL_EXTRA) -> None:
        self._reason = reason

    async def follow_up(self, cloud_id: str, text: str, *, timeout_seconds: int) -> CloudReply:  # noqa: ARG002 -- the port's signature
        """Never runs: ``SessionsUnavailableError``."""
        raise SessionsUnavailableError(self._reason)


class SweptSessions(Protocol):
    """What the runtime drives of ``AgentSessionControl``."""

    async def sweep(self, now: datetime | None = None, *, purge: bool = True) -> None:
        """Apply time; with ``purge``, remove sessions past their retention."""
        ...

    async def shutdown(self) -> None:
        """End every live session ``server_stopped``."""
        ...


class UnfinishedSessions(Protocol):
    """The store's half of a restart: rows a crash left live."""

    def end_unfinished(self, at: datetime, reason: EndReason) -> int:
        """End every session not yet ended; answers how many."""
        ...


class SessionRuntime:
    """The agent sessions' lifecycle in ``hub web`` (see the module docstring)."""

    def __init__(  # noqa: PLR0913 -- the runtime's ports and timings, all injected
        self,
        control: SweptSessions,
        store: UnfinishedSessions,
        *,
        clock: Callable[[], datetime],
        sweep_seconds: float = SWEEP_SECONDS,
        purge_seconds: float = PURGE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._control = control
        self._store = store
        self._clock = clock
        self._sweep_seconds = sweep_seconds
        self._purge_seconds = purge_seconds
        self._monotonic = monotonic
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sweeper: asyncio.Task[None] | None = None
        self._shutdown: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """End what a crash left unfinished, then start sweeping."""
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(self._store.end_unfinished, self._clock(), EndReason.SERVER_STOPPED)
        self._sweeper = asyncio.create_task(self._sweep_forever())

    def begin_exit(self) -> None:
        """Start the shutdown on the loop; safe from a signal handler or another thread."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._begin_shutdown)

    async def stop(self) -> None:
        """Stop sweeping, end every live session and wait until they have ended."""
        self._begin_shutdown()
        if self._sweeper is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
        if self._shutdown is not None:
            await asyncio.shield(self._shutdown)

    def _begin_shutdown(self) -> None:
        if self._shutdown is not None:
            return
        if self._sweeper is not None:
            self._sweeper.cancel()
        self._shutdown = asyncio.get_running_loop().create_task(self._control.shutdown())

    async def _sweep_forever(self) -> None:
        purged_at: float | None = None
        while True:
            now = self._monotonic()
            purge = purged_at is None or now - purged_at >= self._purge_seconds
            try:
                await self._control.sweep(self._clock(), purge=purge)
            except Exception:  # noqa: BLE001 -- one failed sweep never stops the next
                _log.warning("agent session sweep failed", exc_info=True)
            else:
                if purge:
                    purged_at = now
            await asyncio.sleep(self._sweep_seconds)
