"""Bounded child runs and the last-resort stop of a ``claude`` that will not end (P12, D.6).

``run_bounded`` runs a short command (``claude --version``, ``--help``, a cloud follow-up): no
shell, its own session (so its process group can be killed whole), stdin closed, stderr
discarded, stdout read up to a byte limit, and a deadline. Past the limit or the deadline the
group is killed.

A session's ``claude`` is started by the SDK in ``hub web``'s own process group; the SDK closes
stdin, waits, then signals it, and the CLI ends its tools (each in its own session). ``terminate``
is what the driver uses when that takes longer than its shutdown budget: SIGTERM, a grace, then
SIGKILL, on the CLI's own pid.
"""

import asyncio
import os
import signal
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

POLL_SECONDS: Final = 0.05
CHUNK_BYTES: Final = 64 * 1024


class RunTimeoutError(Exception):
    """The command passed its deadline; its process group was killed."""


@dataclass(frozen=True, kw_only=True)
class Completed:
    """How a bounded run ended: exit code (None when stopped for its output), what it wrote
    (at most ``limit + 1`` bytes) and whether it wrote more than ``limit``."""

    code: int | None
    stdout: bytes
    overflow: bool


async def run_bounded(
    argv: Sequence[str],
    *,
    timeout: float,
    limit: int,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
) -> Completed:
    """Run ``argv`` with a deadline and an output limit; see the module docstring."""
    child = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=None if env is None else dict(env),
        cwd=cwd,
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(timeout):
            stdout = await _read(child, limit)
            if len(stdout) > limit:
                _kill_group(child.pid)
                await child.wait()
                return Completed(code=None, stdout=stdout, overflow=True)
            code = await child.wait()
    except TimeoutError:
        _kill_group(child.pid)
        await child.wait()
        raise RunTimeoutError from None
    return Completed(code=code, stdout=stdout, overflow=False)


async def _read(child: asyncio.subprocess.Process, limit: int) -> bytes:
    stream = child.stdout
    if stream is None:
        return b""
    buffer = bytearray()
    while len(buffer) <= limit:
        chunk = await stream.read(CHUNK_BYTES)
        if not chunk:
            break
        buffer += chunk
    return bytes(buffer[: limit + 1])


def _kill_group(pid: int) -> None:
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def alive(pid: int) -> bool:
    """Whether ``pid`` runs; a zombie (ended, not yet waited for) counts as gone."""
    stat = Path(f"/proc/{pid}/stat")
    if Path("/proc/self/stat").exists():
        try:
            fields = stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        except OSError:
            return False
        return fields[0] != "Z"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def terminate(pid: int, *, grace: float) -> bool:
    """SIGTERM ``pid``, wait ``grace`` seconds, then SIGKILL it; True when it had to be killed,
    False when it was already gone or ended within the grace."""
    if not alive(pid):
        return False
    _signal(pid, signal.SIGTERM)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + grace
    while loop.time() < deadline:
        await asyncio.sleep(POLL_SECONDS)
        if not alive(pid):
            return False
    _signal(pid, signal.SIGKILL)
    return True


def _signal(pid: int, signum: int) -> None:
    with suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signum)
