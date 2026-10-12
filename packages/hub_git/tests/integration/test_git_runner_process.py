"""The default launcher against small fake ``git`` executables on a temporary ``PATH``."""

import os
import sys
import time
from pathlib import Path

import pytest

from agent_hub.core.learnings.brain_change_requests import (
    ChangeRequestFailedError,
    ChangeRequestTimeoutError,
)
from agent_hub.hub_git.git_runner import OUTPUT_LIMIT, GitRunner

_SLEEPER = """\
import os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(f"{os.getpid()} {child.pid}")
time.sleep(60)
"""

_TALKER = """\
import os, sys
sys.stdout.write(os.environ.get("GIT_TERMINAL_PROMPT", "unset") + "\\n")
sys.stdout.write("x" * int(sys.argv[1]))
sys.stderr.write("token=not-a-real-one\\n")
sys.exit(int(sys.argv[2]))
"""


def _fake_git(bin_dir: Path, script: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    source = bin_dir / "fake_git.py"
    source.write_text(script)
    git = bin_dir / "git"
    git.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{source}" "$@"\n')
    git.chmod(0o755)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers signal 0; it is dead for our purpose.
    status = Path(f"/proc/{pid}/stat")
    return not (status.exists() and status.read_text().split()[2] == "Z")


def test_raises_timeout_when_deadline_passes(tmp_path: Path) -> None:
    _fake_git(tmp_path / "bin", _SLEEPER)
    pids = tmp_path / "pids"
    runner = GitRunner(environ={"PATH": str(tmp_path / "bin")}, deadline=2.0)
    started = time.monotonic()

    with pytest.raises(ChangeRequestTimeoutError):
        runner.start().git([str(pids)], cwd=tmp_path, step="clone")

    assert time.monotonic() - started < 10
    for pid in map(int, pids.read_text().split()):
        for _ in range(50):
            if not _alive(pid):
                break
            time.sleep(0.1)
        assert not _alive(pid)


def test_reads_bounded_stdout_when_child_succeeds(tmp_path: Path) -> None:
    _fake_git(tmp_path / "bin", _TALKER)
    runner = GitRunner(environ={"PATH": str(tmp_path / "bin")})

    result = runner.start().git([str(OUTPUT_LIMIT * 2), "0"], cwd=tmp_path, step="show")

    assert result.stdout.startswith(b"0\n")
    assert len(result.stdout) == OUTPUT_LIMIT
    assert b"token" not in result.stdout


def test_raises_failed_step_without_output_when_child_fails(tmp_path: Path) -> None:
    _fake_git(tmp_path / "bin", _TALKER)
    runner = GitRunner(environ={"PATH": str(tmp_path / "bin")})

    with pytest.raises(ChangeRequestFailedError) as failed:
        runner.start().git(["10", "3"], cwd=tmp_path, step="push")

    assert failed.value.step == "push"
    assert "token" not in str(failed.value)


def test_reads_no_stdout_when_not_kept(tmp_path: Path) -> None:
    _fake_git(tmp_path / "bin", _TALKER)
    runner = GitRunner(environ={"PATH": str(tmp_path / "bin")}, gh="git")

    result = runner.start().gh(["10", "0"], cwd=tmp_path, step="auth", keep_stdout=False)

    assert result.stdout == b""
