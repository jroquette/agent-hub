"""``scripts/step_guard.py``: a step of ``make check-changed`` in a process group of its own,
ended with everything it started once the run's pipe closes. Real processes, under tmp_path."""

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GUARD = (sys.executable, "-m", "scripts.step_guard")
WAIT_S = 15.0
# A step that starts a grandchild, which beats on a file until it is killed (30 s at most).
GRANDCHILD = """
import sys, time
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    with open(sys.argv[1], "a") as beat:
        beat.write(".")
    time.sleep(0.05)
"""
PARENT = """
import subprocess, sys, time
subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]])
time.sleep(30)
"""


def _guarded(argv: list[str]) -> tuple[subprocess.Popen[bytes], int]:
    """The guard running ``argv``, and the write end of its pipe, which the caller holds."""
    keep, alive = os.pipe()
    try:
        guard = subprocess.Popen(  # noqa: S603 -- the test's own Python, a fixed program
            [*GUARD, str(keep), *argv], cwd=REPO_ROOT, pass_fds=(keep,)
        )
    finally:
        os.close(keep)
    return guard, alive


def _until(check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while not check():
        assert time.monotonic() < deadline, "the step never started its grandchild"
        time.sleep(0.05)


def test_exits_with_step_code_when_step_ends() -> None:
    guard, alive = _guarded([sys.executable, "-c", "raise SystemExit(3)"])
    try:
        code = guard.wait(timeout=WAIT_S)
    finally:
        os.close(alive)

    assert code == 3


def test_ends_step_and_what_it_started_when_pipe_closes(tmp_path: Path) -> None:
    beats = tmp_path / "beats"
    guard, alive = _guarded([sys.executable, "-c", PARENT, GRANDCHILD, str(beats)])
    try:
        _until(lambda: beats.exists() and beats.stat().st_size > 0)
    finally:
        os.close(alive)

    code = guard.wait(timeout=WAIT_S)
    seen = beats.stat().st_size
    time.sleep(0.5)

    assert code != 0
    assert beats.stat().st_size == seen
