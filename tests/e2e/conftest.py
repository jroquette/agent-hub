"""Shared e2e fixtures: e2e tests run real tools as subprocesses, from the repo root by default."""

import os
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_SECONDS = 120
INSTALL_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class InstalledHub:
    """``hub`` installed with ``uv tool install`` into isolated tool dirs."""

    executable: Path
    env: Mapping[str, str]


@pytest.fixture
def repo_root() -> Path:
    """The repository root, where the gate configs (pyproject.toml, mypy.ini) live."""
    return REPO_ROOT


@pytest.fixture
def run() -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run a command and capture its text output; never raises on rc != 0."""

    def _run(
        command: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path = REPO_ROOT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return _run


@pytest.fixture(scope="session")
def installed_hub(tmp_path_factory: pytest.TempPathFactory) -> InstalledHub:
    """Install the meta-package once per session, pinned to uv.lock, into isolated tool dirs.

    The install keeps the real ``HOME`` and ``XDG_*`` so uv finds its warm cache; tests that run
    ``hub`` against a database point ``HOME``/``XDG_DATA_HOME`` at their own ``tmp_path``.
    """
    uv = os.environ.get("UV") or shutil.which("uv")
    assert uv is not None, "uv must be on PATH (run the tests with uv run)"
    tmp_path = tmp_path_factory.mktemp("installed-hub")
    bin_dir = tmp_path / "bin"
    # Isolated tool dirs, so the test never touches the user's installed tools.
    env = {**os.environ, "UV_TOOL_DIR": str(tmp_path / "tools"), "UV_TOOL_BIN_DIR": str(bin_dir)}
    env.pop("VIRTUAL_ENV", None)
    # hub must never write to a database named by the caller's environment.
    env.pop("AGENT_HUB_DB", None)
    constraints = tmp_path / "constraints.txt"
    export_command = [uv, "export", "--locked", "--package", "agent-hub", "--no-emit-workspace"]
    _run_or_fail([*export_command, "--no-hashes", "-o", str(constraints)], env=env)
    meta_package = REPO_ROOT / "packages" / "agent-hub"
    # The interpreter running the tests (a final 3.14 build), so uv never picks an rc build or
    # downloads a managed Python into the real XDG dirs.
    install_command = [uv, "tool", "install", "--python", sys.executable, "-c", str(constraints)]
    # uv reuses a cached build of a local package until its pyproject.toml changes, so a new
    # module would be missing from the installed copy; the members are rebuilt every time.
    for member in _workspace_members():
        install_command += ["--reinstall-package", member]
    _run_or_fail([*install_command, str(meta_package)], env=env, timeout=INSTALL_TIMEOUT_SECONDS)
    return InstalledHub(executable=bin_dir / "hub", env=env)


def _workspace_members() -> list[str]:
    """The distribution name of every workspace package."""
    return sorted(
        tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["name"]
        for pyproject in (REPO_ROOT / "packages").glob("*/pyproject.toml")
    )


def _run_or_fail(
    command: Sequence[str], *, env: Mapping[str, str], timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> None:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# How long ``hub web`` gets to print its URL line, and to exit once interrupted.
WEB_START_SECONDS = 30
WEB_STOP_SECONDS = 15


@dataclass(frozen=True)
class RunningWeb:
    """A ``hub web`` started by the installed ``hub`` on temp paths; ``url`` has no slash."""

    url: str
    port: int
    first_line: str
    db_path: Path
    env: Mapping[str, str]


def free_loopback_port() -> int:
    """A loopback port nothing listens on (bound, then released)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _first_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(timeout=WEB_START_SECONDS):
            return ""
    return process.stdout.readline()


@pytest.fixture
def hub_web(installed_hub: InstalledHub, tmp_path: Path) -> Iterator[RunningWeb]:
    """``hub web --port <free> --db <tmp>``, with HOME and the XDG folders under ``tmp_path``.

    Stopped with SIGINT after the test, as Ctrl+C stops it; its log goes to a file.
    """
    port = free_loopback_port()
    db_path = tmp_path / "data" / "web.db"
    env = {
        **installed_hub.env,
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
    }
    command = [str(installed_hub.executable), "web", "--port", str(port), "--db", str(db_path)]
    with (tmp_path / "web.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=log, text=True
        )
        try:
            line = _first_line(process)
            assert line, (tmp_path / "web.log").read_text(encoding="utf-8")
            yield RunningWeb(
                url=f"http://127.0.0.1:{port}",
                port=port,
                first_line=line,
                db_path=db_path,
                env=env,
            )
        finally:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=WEB_STOP_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
