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

from agent_hub.claude_sessions.testing.scenarios import (
    RECORD_ENV,
    SCENARIO_ENV,
    Scenario,
    StubRecord,
    read_records,
    simple_turn,
    write_scenario,
    write_shim,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_SECONDS = 120
INSTALL_TIMEOUT_SECONDS = 300
# The extra that adds session control to ``hub web`` (the Claude Agent SDK, ADR 0031).
SESSIONS_EXTRA = "sessions"


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
    """Install the meta-package with its ``sessions`` extra once per session, pinned to uv.lock,
    into isolated tool dirs (``uv tool install 'agent-hub[sessions]'``, ADR 0031).

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
    export_command = [
        uv,
        "export",
        "--locked",
        "--package",
        "agent-hub",
        "--extra",
        SESSIONS_EXTRA,
        "--no-emit-workspace",
    ]
    _run_or_fail([*export_command, "--no-hashes", "-o", str(constraints)], env=env)
    meta_package = REPO_ROOT / "packages" / "agent-hub"
    # The interpreter running the tests (a final 3.14 build), so uv never picks an rc build or
    # downloads a managed Python into the real XDG dirs.
    install_command = [uv, "tool", "install", "--python", sys.executable, "-c", str(constraints)]
    # uv reuses a cached build of a local package until its pyproject.toml changes, so a new
    # module would be missing from the installed copy; the members are rebuilt every time.
    for member in _workspace_members():
        install_command += ["--reinstall-package", member]
    requirement = f"agent-hub[{SESSIONS_EXTRA}] @ {meta_package.as_uri()}"
    _run_or_fail([*install_command, requirement], env=env, timeout=INSTALL_TIMEOUT_SECONDS)
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
    process: subprocess.Popen[str]

    @property
    def token(self) -> str:
        """This start's session token, from the URL line (``/?token=``)."""
        return self.first_line.strip().partition("/?token=")[2]


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
def web_extra_env() -> Mapping[str, str]:
    """Variables added to ``hub web``'s environment; a test module overrides this fixture (the
    web smoke puts a fake ``gh`` on ``PATH`` and a git config that maps the hub's remote)."""
    return {}


@pytest.fixture
def hub_web(
    installed_hub: InstalledHub, tmp_path: Path, web_extra_env: Mapping[str, str]
) -> Iterator[RunningWeb]:
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
        **web_extra_env,
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
                process=process,
            )
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=WEB_STOP_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@dataclass(frozen=True)
class StubClaude:
    """A ``claude`` on ``PATH`` that is the stub CLI (P17, E14): ``env`` puts it first on
    ``PATH`` and names its scenario and record files; ``play`` writes the scenario it plays."""

    bin_dir: Path
    scenario_path: Path
    record_path: Path
    env: Mapping[str, str]

    def play(self, scenario: Scenario) -> None:
        """The scenario the stub plays from its next start."""
        self.scenario_path.write_text(scenario.model_dump_json(), encoding="utf-8")

    def records(self) -> list[StubRecord]:
        """What every stub process saw, oldest first."""
        return read_records(self.record_path)


@pytest.fixture
def stub_claude(tmp_path: Path) -> StubClaude:
    """The stub ``claude`` (run by this Python, never a model), playing a simple turn until a
    test sets its scenario. No production switch selects it: it is found on ``PATH``."""
    folder = tmp_path / "stub-claude"
    bin_dir = folder / "bin"
    write_shim(bin_dir)
    scenario_path = write_scenario(folder, Scenario(turns=[simple_turn()]))
    record_path = folder / "record.jsonl"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        SCENARIO_ENV: str(scenario_path),
        RECORD_ENV: str(record_path),
    }
    return StubClaude(bin_dir, scenario_path, record_path, env)
