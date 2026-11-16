"""``hub setup``'s real tool probe (``SubprocessToolProbe``) when a tool fails to answer.

Each tool is a file under ``tmp_path``: one the kernel cannot execute, one that hangs past the
timeout, one that leaves a background grandchild, and one found through a relative ``PATH``.
"""

import contextlib
import os
import signal
import time
from pathlib import Path

import pytest

from agent_hub.cli.setup_tools import SubprocessToolProbe
from agent_hub.core.workspace.setup_checklist import ProbeResult

SHORT_TIMEOUT = 0.2
# Long enough for the tool to start its grandchild and write its pid before the kill.
GRANDCHILD_TIMEOUT = 1.0
# The killed grandchild is reaped by its new parent (init or a subreaper) soon after.
REAP_DEADLINE = 5.0


def _write_tool(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o755)
    return path


def _path_with(folder: Path) -> dict[str, str]:
    """An environment whose ``PATH`` is ``folder``, then the system's (for ``sleep``)."""
    return {"PATH": f"{folder}{os.pathsep}{os.environ.get('PATH', os.defpath)}"}


def _is_gone_within(pid: int, deadline: float) -> bool:
    end = time.monotonic() + deadline
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() > end:
            return False
        time.sleep(0.01)


@pytest.mark.parametrize(
    "content",
    [b"\x7fELF\x00not a real program\n", b"uv --version\n", b"#!/nonexistent/interpreter\n"],
    ids=["bad-binary", "no-shebang", "bad-shebang"],
)
def test_gives_no_answer_when_tool_cannot_execute(tmp_path: Path, *, content: bytes) -> None:
    tool = _write_tool(tmp_path / "bin" / "uv", content)
    probe = SubprocessToolProbe(_path_with(tool.parent), tmp_path)

    result = probe.run([str(tool), "--version"], timeout=SHORT_TIMEOUT)

    assert result == ProbeResult(None, b"", is_timed_out=False)


def test_reports_timeout_when_tool_hangs(tmp_path: Path) -> None:
    tool = _write_tool(tmp_path / "bin" / "uv", b"#!/bin/sh\nexec sleep 30\n")
    probe = SubprocessToolProbe(_path_with(tool.parent), tmp_path)

    result = probe.run([str(tool), "--version"], timeout=SHORT_TIMEOUT)

    assert result == ProbeResult(None, b"", is_timed_out=True)


def test_kills_grandchild_when_tool_times_out(tmp_path: Path) -> None:
    pid_path = tmp_path / "grandchild.pid"
    tool = _write_tool(
        tmp_path / "bin" / "gh",
        f"#!/bin/sh\nsleep 30 &\necho $! > '{pid_path}'\nwait\n".encode(),
    )
    probe = SubprocessToolProbe(_path_with(tool.parent), tmp_path)

    result = probe.run([str(tool), "auth", "status"], timeout=GRANDCHILD_TIMEOUT)

    pid = int(pid_path.read_text(encoding="utf-8"))
    try:
        assert result == ProbeResult(None, b"", is_timed_out=True)
        assert _is_gone_within(pid, REAP_DEADLINE), "the grandchild is still alive"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def test_runs_tool_from_other_cwd_when_path_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_tool(tmp_path / "rel-bin" / "uv", b"#!/bin/sh\necho 'uv 0.9.5'\n")
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(tmp_path)
    probe = SubprocessToolProbe({"PATH": "rel-bin"}, other)

    found = probe.which("uv")

    assert found == os.path.join(os.getcwd(), "rel-bin", "uv")
    assert os.path.isabs(found)
    assert probe.run([found, "--version"], timeout=GRANDCHILD_TIMEOUT) == ProbeResult(
        0, b"uv 0.9.5\n", is_timed_out=False
    )
