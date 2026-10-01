"""``run_child`` with real child processes: streams, exit code, a timeout and a missing tool."""

import sys
import textwrap
import time
from pathlib import Path

import pytest

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.errors import ChildTimedOutError

# The grandchild writes its late file this long after it starts, well after the child's timeout.
GRANDCHILD_DELAY = 1.0
CHILD_TIMEOUT = 0.5


def test_returns_streams_when_child_exits(tmp_path: Path) -> None:
    script = "import os, sys; sys.stdout.write(os.getcwd() + ' ' + os.environ['WORD']);"
    script += " sys.stderr.write('err'); sys.exit(3)"

    result = run_child(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"WORD": "out"},
        timeout=None,
        new_session=False,
    )

    assert result == ChildResult(returncode=3, stdout=f"{tmp_path} out".encode(), stderr=b"err")


def test_kills_group_when_timed_out(tmp_path: Path) -> None:
    grandchild = textwrap.dedent(
        f"""
        import pathlib, time
        pathlib.Path("started").write_text("")
        time.sleep({GRANDCHILD_DELAY})
        pathlib.Path("late").write_text("")
        """
    )
    # The child waits until the grandchild runs, so the timeout always finds both alive.
    child = textwrap.dedent(
        f"""
        import os, subprocess, sys, time
        subprocess.Popen([sys.executable, "-c", {grandchild!r}])
        while not os.path.exists("started"):
            time.sleep(0.01)
        time.sleep(60)
        """
    )

    with pytest.raises(ChildTimedOutError):
        run_child(
            [sys.executable, "-c", child],
            cwd=tmp_path,
            env={},
            timeout=CHILD_TIMEOUT,
            new_session=True,
        )
    time.sleep(GRANDCHILD_DELAY)

    assert (tmp_path / "started").exists()
    assert not (tmp_path / "late").exists()


def test_raises_when_tool_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_child(
            [str(tmp_path / "no-such-tool")],
            cwd=tmp_path,
            env={},
            timeout=None,
            new_session=False,
        )
