"""``run_child`` with real child processes: streams, exit code, a timeout and a missing tool.

The kill probes use a lock, not the wall clock: the grandchild holds an exclusive ``flock`` until
it dies, so the test can take the lock only once the whole process group is gone.
"""

import contextlib
import fcntl
import os
import signal
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path
from types import FrameType

import pytest

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.errors import ChildTimedOutError

# Isolated interpreters: no user site, no site-packages, no environment variables read.
PYTHON = (sys.executable, "-I", "-S")
CHILD_TIMEOUT = 1.0
INTERRUPT_AFTER = 0.3
# Long enough to never end on its own during a test; the probe waits this long at most.
SLEEP_FOREVER = 60
PROBE_DEADLINE = 5.0
GRANDCHILD = textwrap.dedent(
    f"""
    import fcntl, os, time
    lock = open("lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    with open("started.tmp", "w") as started:
        started.write(str(os.getpid()))
    os.replace("started.tmp", "started")
    time.sleep({SLEEP_FOREVER})
    """
)
# The child exits once the grandchild holds the lock. The grandchild keeps the inherited stdout
# open, so the read goes on until the timeout or the interruption, and only a kill of the whole
# group frees the lock: without it the run returns while the grandchild still holds it.
CHILD = textwrap.dedent(
    f"""
    import os, subprocess, sys, time
    subprocess.Popen([sys.executable, "-I", "-S", "-c", {GRANDCHILD!r}])
    while not os.path.exists("started"):
        time.sleep(0.01)
    """
)


class Interrupted(Exception):  # noqa: N818 - a test sentinel, not an error
    """Raised by the test's SIGALRM handler in the middle of ``run_child``."""


@contextlib.contextmanager
def grandchild_reaped(folder: Path) -> Iterator[None]:
    """After the block, assert the grandchild started and died; kill it if it is still alive."""
    try:
        yield
        assert (folder / "started").exists(), "the grandchild never started"
        assert is_lock_free_within(folder / "lock", PROBE_DEADLINE), "the grandchild is alive"
    finally:
        with contextlib.suppress(FileNotFoundError, ProcessLookupError, ValueError):
            os.kill(int((folder / "started").read_text()), signal.SIGKILL)


def is_lock_free_within(lock_path: Path, deadline: float) -> bool:
    end = time.monotonic() + deadline
    # "r+": a missing lock file raises instead of being created free.
    with lock_path.open("r+") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() > end:
                    return False
                time.sleep(0.01)
            else:
                return True


def test_returns_streams_when_child_exits(tmp_path: Path) -> None:
    script = "import os, sys; sys.stdout.write(os.getcwd() + ' ' + os.environ['WORD']);"
    script += " sys.stderr.write('err'); sys.exit(3)"

    result = run_child([*PYTHON, "-c", script], cwd=tmp_path, env={"WORD": "out"}, timeout=None)

    assert result == ChildResult(returncode=3, stdout=f"{tmp_path} out".encode(), stderr=b"err")


def test_kills_group_when_timed_out(tmp_path: Path) -> None:
    with grandchild_reaped(tmp_path), pytest.raises(ChildTimedOutError):
        run_child([*PYTHON, "-c", CHILD], cwd=tmp_path, env={}, timeout=CHILD_TIMEOUT)


def test_kills_group_when_interrupted(tmp_path: Path) -> None:
    def interrupt(_signal: int, _frame: FrameType | None) -> None:
        raise Interrupted

    previous = signal.signal(signal.SIGALRM, interrupt)
    try:
        with grandchild_reaped(tmp_path), pytest.raises(Interrupted):
            signal.setitimer(signal.ITIMER_REAL, INTERRUPT_AFTER)
            run_child([*PYTHON, "-c", CHILD], cwd=tmp_path, env={}, timeout=SLEEP_FOREVER / 2)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_raises_when_tool_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_child([str(tmp_path / "no-such-tool")], cwd=tmp_path, env={}, timeout=None)


def test_keeps_caller_group_when_own_session_off(tmp_path: Path) -> None:
    # A timed-out child in the caller's group is killed alone; what it started stays in the
    # caller's group, so a kill of that group (the SessionStart hook's) still reaches it.
    with grandchild_reaped_by_caller(tmp_path), pytest.raises(ChildTimedOutError):
        run_child(
            [*PYTHON, "-c", CHILD], cwd=tmp_path, env={}, timeout=CHILD_TIMEOUT, own_session=False
        )

    assert (tmp_path / "group").read_text() == str(os.getpgrp())


@contextlib.contextmanager
def grandchild_reaped_by_caller(folder: Path) -> Iterator[None]:
    """After the block, the grandchild runs in this process's group; it is killed afterwards."""
    try:
        yield
        assert (folder / "started").exists(), "the grandchild never started"
        pid = int((folder / "started").read_text())
        (folder / "group").write_text(str(os.getpgid(pid)))
    finally:
        with contextlib.suppress(FileNotFoundError, ProcessLookupError, ValueError):
            os.kill(int((folder / "started").read_text()), signal.SIGKILL)
