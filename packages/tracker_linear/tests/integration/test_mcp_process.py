"""The default runner of the Linear MCP adapter against a fake ``claude`` executable (E8).

The fake is a ``/bin/sh`` wrapper that ``exec``s a Python script, so the process the runner
starts is the script itself. The script writes what it saw (its process group and session,
cwd, environment names, argv, stdin) to a record file, then answers or hangs.
"""

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_hub.tracker_linear.claude_process import (
    CLAUDE_PROGRAM,
    ClaudeOutput,
    run_claude,
)

pytestmark = pytest.mark.disable_socket

# Names a /bin/sh may add to the environment it passes on (dash: PWD; bash as sh: SHLVL, _).
_SHELL_NAMES = {"PWD", "OLDPWD", "SHLVL", "_"}

_FAKE_SCRIPT = """\
import fcntl, json, os, subprocess, sys, time

mode = os.environ["FAKE_CLAUDE_MODE"]
if mode == "hang":
    lock = open(os.environ["FAKE_CLAUDE_LOCK"], "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
record = {
    "pid": os.getpid(),
    "pgid": os.getpgid(0),
    "sid": os.getsid(0),
    "cwd": os.getcwd(),
    "env": sorted(os.environ),
    "argv": sys.argv[1:],
    "stdin_is_devnull": os.path.samestat(os.fstat(0), os.stat(os.devnull)),
}
if mode == "hang":
    # A grandchild holding stdout and stderr open: the runner must not wait for it.
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    record["grandchild"] = grandchild.pid
path = os.environ["FAKE_CLAUDE_RECORD"]
with open(path + ".tmp", "w") as stream:
    json.dump(record, stream)
os.replace(path + ".tmp", path)
if mode in {"hang", "sleep"}:
    while True:
        time.sleep(1)
if mode == "big":
    # More than a pipe buffer on each stream: the runner must drain both while waiting.
    sys.stderr.write("e" * (1 << 20))
    sys.stdout.write("o" * (1 << 20))
    sys.exit(0)
print(json.dumps({"type": "result", "result": "answer"}))
print("a line on stderr", file=sys.stderr)
sys.exit(int(os.environ["FAKE_CLAUDE_EXIT"]))
"""


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    """A directory holding only the fake ``claude``."""
    script = tmp_path / "fake_claude.py"
    script.write_text(_FAKE_SCRIPT)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / CLAUDE_PROGRAM
    wrapper.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{script}' \"$@\"\n")
    wrapper.chmod(0o755)
    return bin_dir


@pytest.fixture
def hub_root(tmp_path: Path) -> Path:
    root = tmp_path / "hub"
    root.mkdir()
    return root.resolve()


def _env(
    tmp_path: Path, bin_dir: Path, *, mode: str = "answer", exit_code: int = 0
) -> dict[str, str]:
    return {
        "PATH": str(bin_dir),
        "PYTHONCOERCECLOCALE": "0",
        "FAKE_CLAUDE_MODE": mode,
        "FAKE_CLAUDE_EXIT": str(exit_code),
        "FAKE_CLAUDE_RECORD": str(tmp_path / "record.json"),
        "FAKE_CLAUDE_LOCK": str(tmp_path / "claude.lock"),
    }


def _record(tmp_path: Path) -> dict[str, object]:
    record: dict[str, object] = json.loads((tmp_path / "record.json").read_text())
    return record


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def grandchildren() -> Iterator[list[int]]:
    """Pids a test saw started by the fake; each is killed at teardown."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        if _is_running(pid):
            os.kill(pid, signal.SIGKILL)


@pytest.fixture
def stdin_pipe() -> Iterator[None]:
    """The caller's fd 0 is a pipe, so a child that inherited it would not see /dev/null."""
    read_end, write_end = os.pipe()
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        yield
    finally:
        os.dup2(saved, 0)
        for descriptor in (saved, read_end, write_end):
            os.close(descriptor)


def test_keeps_caller_group_when_claude_runs(
    tmp_path: Path, fake_bin: Path, hub_root: Path
) -> None:
    run_claude(
        [CLAUDE_PROGRAM, "-p", "x"], cwd=hub_root, env=_env(tmp_path, fake_bin), timeout_s=30.0
    )

    record = _record(tmp_path)
    assert record["pgid"] == os.getpgrp()
    assert record["sid"] == os.getsid(0)


def test_passes_env_and_cwd_when_called(
    tmp_path: Path, fake_bin: Path, hub_root: Path, *, stdin_pipe: None
) -> None:
    env = _env(tmp_path, fake_bin, exit_code=3)
    argv = [CLAUDE_PROGRAM, "-p", "two words", "--output-format", "json"]

    output = run_claude(argv, cwd=hub_root, env=env, timeout_s=30.0)

    record = _record(tmp_path)
    assert record["cwd"] == str(hub_root)
    seen = set(record["env"])  # type: ignore[call-overload]
    assert seen - _SHELL_NAMES == set(env)
    assert record["argv"] == argv[1:]
    assert record["stdin_is_devnull"] is True
    assert output == ClaudeOutput(
        returncode=3,
        stdout=b'{"type": "result", "result": "answer"}\n',
        stderr=b"a line on stderr\n",
    )


def test_kills_child_when_timeout_passes(
    tmp_path: Path, fake_bin: Path, hub_root: Path, *, grandchildren: list[int]
) -> None:
    env = _env(tmp_path, fake_bin, mode="hang")

    # The test asserts outcomes, not the clock: 10 s only leaves a slow runner time to start
    # the fake and take the lock before the deadline.
    with pytest.raises(TimeoutError, match=r"claude timed out after 10 s"):
        run_claude([CLAUDE_PROGRAM, "-p", "x"], cwd=hub_root, env=env, timeout_s=10.0)

    # The child started and took the lock; the lock is free now because the child is gone.
    record = _record(tmp_path)
    grandchildren.append(int(record["grandchild"]))  # type: ignore[call-overload]
    assert record["pgid"] == os.getpgrp()
    with (tmp_path / "claude.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert not _is_running(int(record["pid"]))  # type: ignore[call-overload]
    # The runner returned although a grandchild still held its output pipes.
    assert _is_running(grandchildren[0])


def test_raises_when_claude_missing(tmp_path: Path, fake_bin: Path, hub_root: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {**_env(tmp_path, fake_bin), "PATH": str(empty)}

    with pytest.raises(FileNotFoundError, match="claude"):
        run_claude([CLAUDE_PROGRAM, "-p", "x"], cwd=hub_root, env=env, timeout_s=30.0)

    assert not (tmp_path / "record.json").exists()


def test_resolves_claude_on_child_path_when_caller_path_differs(
    tmp_path: Path, fake_bin: Path, hub_root: Path, *, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))

    run_claude(
        [CLAUDE_PROGRAM, "-p", "x"], cwd=hub_root, env=_env(tmp_path, fake_bin), timeout_s=30.0
    )

    assert _record(tmp_path)["cwd"] == str(hub_root)


@pytest.mark.parametrize("path", ["", None], ids=["empty", "absent"])
def test_raises_when_child_path_empty_or_absent(
    tmp_path: Path,
    fake_bin: Path,
    hub_root: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
    path: str | None,
) -> None:
    # The caller's PATH finds the fake; the child's must not fall back to it.
    monkeypatch.setenv("PATH", str(fake_bin))
    env = {name: value for name, value in _env(tmp_path, fake_bin).items() if name != "PATH"}
    if path is not None:
        env["PATH"] = path

    with pytest.raises(FileNotFoundError, match="claude"):
        run_claude([CLAUDE_PROGRAM, "-p", "x"], cwd=hub_root, env=env, timeout_s=30.0)


def test_returns_all_output_when_streams_exceed_pipe_buffer(
    tmp_path: Path, fake_bin: Path, hub_root: Path
) -> None:
    env = _env(tmp_path, fake_bin, mode="big")

    output = run_claude([CLAUDE_PROGRAM, "-p", "x"], cwd=hub_root, env=env, timeout_s=30.0)

    assert output == ClaudeOutput(returncode=0, stdout=b"o" * (1 << 20), stderr=b"e" * (1 << 20))


def test_resolves_relative_path_entry_when_cwd_differs(
    tmp_path: Path, fake_bin: Path, hub_root: Path, *, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "bin" names the fake from the caller's cwd, not from the child's cwd (the hub root).
    monkeypatch.chdir(tmp_path)
    env = {**_env(tmp_path, fake_bin), "PATH": fake_bin.name}

    run_claude([CLAUDE_PROGRAM, "-p", "x"], cwd=hub_root, env=env, timeout_s=30.0)

    assert _record(tmp_path)["cwd"] == str(hub_root)


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 30
    while not path.exists():
        assert time.monotonic() < deadline, f"{path.name} never appeared"
        time.sleep(0.01)


def test_reaps_child_when_interrupted(
    tmp_path: Path, fake_bin: Path, hub_root: Path, *, monkeypatch: pytest.MonkeyPatch
) -> None:
    children: list[subprocess.Popen[bytes]] = []

    def interrupted(child: subprocess.Popen[bytes], timeout: float | None = None) -> None:
        children.append(child)
        _wait_for(tmp_path / "record.json")
        # Popen's exit waits 0.25 s for a child after Ctrl-C; with 0, only the runner reaps.
        child._sigint_wait_secs = 0  # type: ignore[attr-defined]
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    env = _env(tmp_path, fake_bin, mode="sleep")

    with pytest.raises(KeyboardInterrupt):
        run_claude([CLAUDE_PROGRAM, "-p", "x"], cwd=hub_root, env=env, timeout_s=30.0)

    [child] = children
    assert child.returncode == -signal.SIGKILL
    with pytest.raises(ChildProcessError):
        os.waitpid(child.pid, os.WNOHANG)
