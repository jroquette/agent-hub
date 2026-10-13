import asyncio
import threading
from datetime import UTC, datetime

import pytest

from agent_hub.api.agent_session_runtime import (
    INSTALL_EXTRA,
    SessionRuntime,
    UnavailableSessionDriver,
)
from agent_hub.core.agent_sessions.agent_session import EndReason
from agent_hub.core.agent_sessions.driver import DriverHandle, PermissionMode, StartSpec
from agent_hub.core.agent_sessions.errors import SessionsUnavailableError

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


class FakeControl:
    """Records each sweep (``purge`` flag) and the shutdown; ``failing`` sweeps raise."""

    def __init__(self, *, failing: int = 0) -> None:
        self.sweeps: list[bool] = []
        self.shutdowns = 0
        self.failing = failing
        self.swept = asyncio.Event()
        self.shutdown_started = asyncio.Event()
        self.release_shutdown = asyncio.Event()
        self.release_shutdown.set()

    async def sweep(self, now: datetime | None = None, *, purge: bool = True) -> None:
        assert now == NOW
        self.sweeps.append(purge)
        self.swept.set()
        if self.failing:
            self.failing -= 1
            msg = "store busy"
            raise RuntimeError(msg)

    async def shutdown(self) -> None:
        self.shutdowns += 1
        self.shutdown_started.set()
        await self.release_shutdown.wait()


class FakeStore:
    def __init__(self) -> None:
        self.ended: list[tuple[datetime, EndReason]] = []

    def end_unfinished(self, at: datetime, reason: EndReason) -> int:
        self.ended.append((at, reason))
        return 1


class Ticks:
    """A monotonic clock that moves ``step`` seconds each time it is read."""

    def __init__(self, step: float) -> None:
        self.at = 0.0
        self.step = step

    def __call__(self) -> float:
        now = self.at
        self.at += self.step
        return now


def _runtime(control: FakeControl, store: FakeStore, *, step: float = 1000.0) -> SessionRuntime:
    return SessionRuntime(
        control, store, clock=lambda: NOW, sweep_seconds=0.001, monotonic=Ticks(step)
    )


async def _sweeps(control: FakeControl, count: int) -> None:
    async with asyncio.timeout(5):
        while len(control.sweeps) < count:
            await asyncio.sleep(0.001)


async def test_ends_unfinished_sessions_when_runtime_starts() -> None:
    control, store = FakeControl(), FakeStore()
    runtime = _runtime(control, store)

    await runtime.start()
    await runtime.stop()

    assert store.ended == [(NOW, EndReason.SERVER_STOPPED)]


async def test_purges_first_then_hourly_when_sweeping() -> None:
    control, store = FakeControl(), FakeStore()
    runtime = _runtime(control, store)

    await runtime.start()
    await _sweeps(control, 6)
    await runtime.stop()

    # Each tick reads 1000 s later: a purge at start, then every fourth tick (3600 s).
    assert control.sweeps[:6] == [True, False, False, False, True, False]


async def test_keeps_sweeping_when_one_sweep_fails() -> None:
    control, store = FakeControl(failing=2), FakeStore()
    runtime = _runtime(control, store)

    await runtime.start()
    await _sweeps(control, 3)
    await runtime.stop()

    # A failed purge is tried again on the next tick.
    assert control.sweeps[:3] == [True, True, True]


async def test_stops_sweeping_and_waits_for_shutdown_when_stopped() -> None:
    control, store = FakeControl(), FakeStore()
    runtime = _runtime(control, store)
    await runtime.start()
    await _sweeps(control, 1)
    control.release_shutdown.clear()

    stopping = asyncio.create_task(runtime.stop())
    await control.shutdown_started.wait()
    swept = len(control.sweeps)
    await asyncio.sleep(0.01)
    still_waiting = not stopping.done()
    control.release_shutdown.set()
    await stopping

    assert still_waiting
    assert len(control.sweeps) == swept
    assert control.shutdowns == 1


async def test_begins_shutdown_once_when_exit_signalled_from_another_thread() -> None:
    control, store = FakeControl(), FakeStore()
    runtime = _runtime(control, store)
    await runtime.start()

    signaller = threading.Thread(target=runtime.begin_exit)
    signaller.start()
    signaller.join()
    async with asyncio.timeout(5):
        await control.shutdown_started.wait()
    runtime.begin_exit()
    await runtime.stop()

    assert control.shutdowns == 1


async def test_ignores_exit_when_runtime_never_started() -> None:
    control, store = FakeControl(), FakeStore()

    _runtime(control, store).begin_exit()

    assert control.shutdowns == 0


async def test_says_install_extra_when_driver_unavailable() -> None:
    driver = UnavailableSessionDriver()

    capabilities = await driver.capabilities()

    assert capabilities.available is False
    assert capabilities.reason == INSTALL_EXTRA
    assert await driver.list_resumable("/work/demo-hub") == ()


async def test_refuses_every_command_when_driver_unavailable() -> None:
    driver = UnavailableSessionDriver("no claude")
    handle = DriverHandle("none")
    mode: PermissionMode = "default"
    spec = StartSpec(cwd="/work/demo-hub", mode=mode)

    for command in (
        driver.start(spec),
        driver.send(handle, "hi"),
        driver.interrupt(handle),
        driver.set_mode(handle, mode),
        driver.set_model(handle, None),
    ):
        with pytest.raises(SessionsUnavailableError, match="no claude"):
            await command
    with pytest.raises(SessionsUnavailableError):
        await anext(driver.events(handle))
    await driver.close(handle)
