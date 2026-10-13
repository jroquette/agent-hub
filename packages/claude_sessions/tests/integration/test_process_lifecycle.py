"""Closing sessions leaves no ``claude`` and no tool behind, within budget (AC-165.23, P12)."""

import asyncio
import os
import signal
import time
from contextlib import suppress
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeSDKClient

from agent_hub.claude_sessions.process_tree import alive
from agent_hub.claude_sessions.sdk_driver import ClaudeSdkSessionDriver
from agent_hub.claude_sessions.testing.scenarios import (
    RECORD_ENV,
    SCENARIO_ENV,
    Scenario,
    StubRecord,
    held_turn,
    read_records,
    write_scenario,
    write_shim,
)
from agent_hub.core.agent_sessions.driver import DriverHandle, StartSpec, TextDelta

pytestmark = pytest.mark.anyio

SHUTDOWN_BUDGET_SECONDS = 5.0


class DeafClient(ClaudeSDKClient):
    """A client whose interrupt never reaches the CLI, so the CLI keeps its turn open."""

    async def interrupt(self) -> None:
        return None


def _driver(tmp_path: Path, **options: object) -> tuple[ClaudeSdkSessionDriver, Path]:
    scenario = Scenario(turns=[held_turn()], grandchild=True, linger_on_eof=True)
    record = tmp_path / "record.jsonl"
    environ = {
        **os.environ,
        "PATH": f"{write_shim(tmp_path / 'bin').parent}{os.pathsep}{os.environ.get('PATH', '')}",
        SCENARIO_ENV: str(write_scenario(tmp_path, scenario)),
        RECORD_ENV: str(record),
    }
    driver = ClaudeSdkSessionDriver(environ=environ, lister=lambda _d, _l: [], **options)
    return driver, record


async def _working(driver: ClaudeSdkSessionDriver, cwd: Path) -> DriverHandle:
    handle = await driver.start(StartSpec(cwd=str(cwd), mode="default"))
    await driver.send(handle, "long task")
    async for event in driver.events(handle):
        if isinstance(event, TextDelta):
            break
    return handle


def _pids(record: Path) -> list[int]:
    spawns: list[StubRecord] = [r for r in read_records(record) if r.event == "spawn"]
    return [pid for r in spawns for pid in (r.pid, r.grandchild_pid) if pid is not None]


def _left(pids: list[int], within: float) -> list[int]:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline and any(alive(pid) for pid in pids):
        time.sleep(0.05)
    return [pid for pid in pids if alive(pid)]


def _kill(pids: list[int]) -> None:
    for pid in pids:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


async def test_leaves_no_child_when_two_sessions_closed_on_shutdown(tmp_path: Path) -> None:
    driver, record = _driver(tmp_path)
    cwd = tmp_path / "work"
    cwd.mkdir()
    handles = [await _working(driver, cwd), await _working(driver, cwd)]
    pids = _pids(record)
    assert len(pids) == 4

    started = time.monotonic()
    await asyncio.gather(*(driver.close(handle) for handle in handles))
    took = time.monotonic() - started

    try:
        assert took < SHUTDOWN_BUDGET_SECONDS
        assert _left(pids, 1.0) == []
    finally:
        _kill(pids)


async def test_stops_cli_when_it_ignores_interrupt_and_closed_stdin(tmp_path: Path) -> None:
    driver, record = _driver(tmp_path, client_factory=DeafClient)
    cwd = tmp_path / "work"
    cwd.mkdir()
    handle = await _working(driver, cwd)
    pids = _pids(record)

    started = time.monotonic()
    await driver.close(handle)
    took = time.monotonic() - started

    try:
        assert took < SHUTDOWN_BUDGET_SECONDS - 1
        assert _left(pids, 1.0) == []
    finally:
        _kill(pids)
