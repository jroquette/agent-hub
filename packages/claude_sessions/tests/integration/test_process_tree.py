"""Bounded child runs and the last-resort stop of a CLI that will not end (P12, D.6)."""

import asyncio
import os
import signal
import sys
import time

import pytest

from agent_hub.claude_sessions.process_tree import (
    RunTimeoutError,
    alive,
    run_bounded,
    terminate,
)

pytestmark = pytest.mark.anyio

PYTHON = sys.executable


async def test_returns_code_and_output_when_child_finishes() -> None:
    done = await run_bounded(
        [PYTHON, "-c", "import sys; print('2.1.296 (Claude Code)'); sys.exit(3)"],
        timeout=10,
        limit=1024,
    )

    assert (done.code, done.stdout, done.overflow) == (3, b"2.1.296 (Claude Code)\n", False)


async def test_stops_child_when_output_over_limit() -> None:
    done = await run_bounded(
        [
            PYTHON,
            "-c",
            "import sys, time; sys.stdout.write('x' * 5000); sys.stdout.flush(); time.sleep(30)",
        ],
        timeout=10,
        limit=1024,
    )

    assert done.overflow
    assert len(done.stdout) <= 1025


async def test_times_out_and_kills_group_when_child_hangs() -> None:
    started = time.monotonic()

    with pytest.raises(RunTimeoutError):
        await run_bounded([PYTHON, "-c", "import time; time.sleep(30)"], timeout=0.5, limit=1024)

    assert time.monotonic() - started < 5


async def test_kills_process_when_it_ignores_sigterm() -> None:
    code = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('up', flush=True); time.sleep(30)"
    )
    child = await asyncio.create_subprocess_exec(PYTHON, "-c", code, stdout=asyncio.subprocess.PIPE)
    assert child.stdout is not None
    await child.stdout.readline()

    killed = await terminate(child.pid, grace=0.3)
    await asyncio.wait_for(child.wait(), 5)

    assert killed
    assert child.returncode == -signal.SIGKILL
    assert not alive(child.pid)


async def test_reports_gone_when_process_already_ended() -> None:
    child = await asyncio.create_subprocess_exec(PYTHON, "-c", "pass")
    await child.wait()

    assert not alive(child.pid)
    assert await terminate(child.pid, grace=0.1) is False
    assert alive(os.getpid())
