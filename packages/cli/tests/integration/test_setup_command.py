"""``hub setup``: one-command onboarding of a developer's machine (AGH-71).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``) whose git is
``env_traced_git``: each call is logged with its environment, then the real git runs. The tests
replace only the command's seams: the tool probe (``setup_tools.tool_probe``), the terminal
check of the prompt (``setup_identity.stdin_is_tty``) and the network timeout
(``setup_repos.NETWORK_TIMEOUT_SECONDS``).
"""

import json
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli import setup_tools
from agent_hub.cli.main import app
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.workspace.setup_checklist import (
    CLAUDE_FIX,
    GH_FIX,
    GIT_FIX,
    PYTHON_FIX,
    TRACKER_KEY_FIX,
    UV_FIX,
    ProbeResult,
)

# The conftest's fixtures (tests cannot import a conftest in importlib mode).
type Workspace = Any
type TracedGit = Any
type SetupRunner = Callable[..., Result]

OLD_PIN = "0.0.1"
SYNTHETIC_KEY = "lin" + "_api_" + "x" * 12
KEY_VARIABLE = "LINEAR_API_KEY"
# Where the fake probe says each tool is; never run, only named in argv.
TOOL_PATHS: Mapping[str, str | None] = {
    name: f"/opt/fake-tools/{name}" for name in ("uv", "git", "python3", "claude", "gh")
}
TOOL_RESULTS: Mapping[str, ProbeResult] = {
    "uv": ProbeResult(0, b"uv 0.9.5 (abc 2025-09-30)\n", is_timed_out=False),
    "python3": ProbeResult(0, b"Python 3.12.4\n", is_timed_out=False),
    "gh": ProbeResult(0, b"", is_timed_out=False),
}
TOOL_LINES_OK = [
    "ok      uv: 0.9.5",
    "ok      git: on PATH",
    "ok      python3: 3.12.4",
    "ok      claude: on PATH",
    "ok      gh: logged in",
]
TRACKER_OK = "ok      tracker: LINEAR_API_KEY set (transport api)"
TRACKER_NO_KEY = (
    f"missing tracker: LINEAR_API_KEY is not set (transport api) Fix: {TRACKER_KEY_FIX}"
)
TRACKER_MCP_OK = (
    "ok      tracker: transport mcp: Linear through claude -p"
    " (its Linear MCP server is not checked)"
)
TRACKER_MCP_NO_CLAUDE = f"missing tracker: transport mcp needs claude on PATH Fix: {CLAUDE_FIX}"
TIMED_OUT = ProbeResult(None, b"", is_timed_out=True)


class FakeToolProbe:
    """Answers ``which`` from ``paths`` and ``run`` from ``results``, by tool name; records the
    ``(argv, timeout)`` of each run."""

    def __init__(self, paths: Mapping[str, str | None], results: Mapping[str, ProbeResult]) -> None:
        self.paths = dict(paths)
        self.results = dict(results)
        self.runs: list[tuple[tuple[str, ...], float]] = []

    def which(self, name: str) -> str | None:
        return self.paths.get(name)

    def run(self, argv: Sequence[str], *, timeout: float) -> ProbeResult:
        self.runs.append((tuple(argv), timeout))
        return self.results[Path(argv[0]).name]


@pytest.fixture
def run_setup(monkeypatch: pytest.MonkeyPatch) -> SetupRunner:
    """Run ``hub setup <args>`` in process with ``root`` as the current folder; ``input`` is
    its stdin."""

    def run(root: Path, *args: str, input: str | None = None) -> Result:
        monkeypatch.chdir(root)
        return CliRunner().invoke(app, ["setup", *args], input=input)

    return run


type ProbeInstaller = Callable[..., FakeToolProbe]


@pytest.fixture
def install_probe(monkeypatch: pytest.MonkeyPatch) -> ProbeInstaller:
    """Replace ``setup_tools.tool_probe`` with a ``FakeToolProbe``: every tool present and
    current, but for the ``paths`` and ``results`` given."""

    def install(
        paths: Mapping[str, str | None] | None = None,
        results: Mapping[str, ProbeResult] | None = None,
    ) -> FakeToolProbe:
        probe = FakeToolProbe({**TOOL_PATHS, **(paths or {})}, {**TOOL_RESULTS, **(results or {})})
        monkeypatch.setattr(setup_tools, "tool_probe", lambda _environ, *, cwd: probe)
        return probe

    return install


@pytest.fixture
def tools_ok(install_probe: ProbeInstaller, monkeypatch: pytest.MonkeyPatch) -> FakeToolProbe:
    """Every tool present and current, and a synthetic ``LINEAR_API_KEY``: all six tool items
    are ok."""
    monkeypatch.setenv(KEY_VARIABLE, SYNTHETIC_KEY)
    return install_probe()


def _edit_hub_json(hub: Path, change: Callable[[dict[str, Any]], None]) -> None:
    path = hub / "hub.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


class TestFixtures:
    def test_logs_env_and_runs_git_when_env_traced_git_used(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, tmp_path: Path
    ) -> None:
        demo_workspace.rewrite_github()
        demo_workspace.init_hub_repo("git@github.com:acme/demo-hub.git")
        git = str(env_traced_git.bin_dir / "git")
        clone = tmp_path / "clone"
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "LINEAR_API_KEY": SYNTHETIC_KEY,
        }

        # Popen, for each child's pid: the traced git execs, so it logs its own.
        with subprocess.Popen(  # noqa: S603 - the traced git, fixed arguments, tmp_path folders
            [git, "clone", "--quiet", "https://github.com/acme/demo-web.git", str(clone)],
            cwd=tmp_path,
            env=env,
        ) as cloning:
            assert cloning.wait() == 0
        with subprocess.Popen(  # noqa: S603 - the traced git, fixed arguments
            [git, "config", "--get", "remote.origin.url"],
            cwd=demo_workspace.hub,
            env={**os.environ, "GIT_DIR": str(demo_workspace.hub / ".git")},
            stdout=subprocess.PIPE,
        ) as reading:
            origin_url, _ = reading.communicate()
        assert reading.returncode == 0

        assert (clone / "README.md").read_text(encoding="utf-8") == "# demo-web\n"
        assert origin_url == b"git@github.com:acme/demo-hub.git\n"
        assert [tuple(call) for call in env_traced_git.calls()] == [
            (
                os.path.realpath(tmp_path),
                f"clone --quiet https://github.com/acme/demo-web.git {clone}",
                "0",
                False,
                True,
                cloning.pid,
            ),
            (
                os.path.realpath(demo_workspace.hub),
                "config --get remote.origin.url",
                "unset",
                True,
                False,
                reading.pid,
            ),
        ]

    def test_logs_no_workspace_call_when_env_traced_git_used(
        self, demo_workspace: Workspace, env_traced_git: TracedGit
    ) -> None:
        before = demo_workspace.origin_head("demo-api")

        after = demo_workspace.advance("demo-api")
        demo_workspace.git(demo_workspace.ws / "demo-api", "fetch", "-q", "origin")

        assert after != before
        assert env_traced_git.calls() == []


class TestExit:
    @pytest.mark.parametrize(
        ("args", "problem"),
        [(("--bogus",), "No such option: --bogus"), (("extra",), "unexpected extra argument")],
        ids=["option", "argument"],
    )
    def test_exits_two_when_usage_wrong(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        args: tuple[str, ...],
        problem: str,
    ) -> None:
        result = run_setup(demo_workspace.hub, *args)

        assert result.exit_code == 2, result.output
        assert result.stdout == ""
        assert problem in unstyle(result.stderr)
        assert env_traced_git.calls() == []

    def test_exits_two_when_not_a_hub(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        elsewhere = os.path.realpath(demo_workspace.ws)

        result = run_setup(demo_workspace.ws)

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{elsewhere}: not a hub: no hub.json in this folder"
            " (hub setup runs in the hub folder or through ./hub)\n"
        )
        assert env_traced_git.calls() == []

    @pytest.mark.parametrize("case", ["schema", "pin-mismatch"])
    def test_exits_one_without_git_when_hub_json_invalid(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        case: str,
    ) -> None:
        if case == "schema":
            (demo_workspace.hub / "hub.json").write_text('{"schema_version": 1}\n')
            expected = 'hub.json: platform: required: the pinned release, as {"version": "1.2.3"}\n'
        else:
            _edit_hub_json(
                demo_workspace.hub,
                lambda document: document["platform"].update(version=OLD_PIN),
            )
            expected = (
                f"hub.json: platform.version: this hub is pinned to {OLD_PIN} but this hub"
                f" command is {version('agent-hub-cli')}; run the pinned release:"
                f" {PINNED_RELEASE_COMMAND.format(version=OLD_PIN)}\n"
            )

        result = run_setup(demo_workspace.hub)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == expected
        assert env_traced_git.calls() == []


def _write_tool(folder: Path, name: str, *, log_path: Path, output: str) -> None:
    """A ``/bin/sh`` tool that logs ``<name>:set`` when ``LINEAR_API_KEY`` reaches it (else
    ``<name>:``), then prints ``output`` and exits 0."""
    script = folder / name
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "{name}:${{LINEAR_API_KEY+set}}" >> {shlex.quote(str(log_path))}\n'
        f"printf '%s\\n' {shlex.quote(output)}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


class TestTools:
    @pytest.mark.parametrize(
        ("paths", "results", "position", "line"),
        [
            pytest.param({}, {}, 0, "ok      uv: 0.9.5", id="uv-ok"),
            pytest.param(
                {},
                {"uv": ProbeResult(0, b"uv 0.9.0\n", is_timed_out=False)},
                0,
                "ok      uv: 0.9.0",
                id="uv-minimum",
            ),
            pytest.param(
                {},
                {"uv": ProbeResult(0, b"uv 0.8.24\n", is_timed_out=False)},
                0,
                "missing uv: 0.8.24, need 0.9.0 or newer Fix: uv self update",
                id="uv-old",
            ),
            pytest.param(
                {"uv": None}, {}, 0, f"missing uv: not on PATH Fix: {UV_FIX}", id="uv-absent"
            ),
            pytest.param(
                {},
                {"uv": TIMED_OUT},
                0,
                "missing uv: timed out after 10 s Fix: uv --version",
                id="uv-timeout",
            ),
            pytest.param(
                {},
                {"uv": ProbeResult(0, b"garbage\n", is_timed_out=False)},
                0,
                "missing uv: cannot read its version Fix: uv --version",
                id="uv-unreadable",
            ),
            pytest.param(
                {"git": None}, {}, 1, f"missing git: not on PATH Fix: {GIT_FIX}", id="git-absent"
            ),
            pytest.param(
                {},
                {"python3": ProbeResult(0, b"Python 3.9.0\n", is_timed_out=False)},
                2,
                "ok      python3: 3.9.0",
                id="python3-minimum",
            ),
            pytest.param(
                {},
                {"python3": ProbeResult(0, b"Python 3.8.18\n", is_timed_out=False)},
                2,
                f"missing python3: 3.8.18, need 3.9 or newer Fix: {PYTHON_FIX}",
                id="python3-old",
            ),
            pytest.param(
                {"python3": None},
                {},
                2,
                f"missing python3: not on PATH Fix: {PYTHON_FIX}",
                id="python3-absent",
            ),
            pytest.param(
                {"claude": None},
                {},
                3,
                f"missing claude: not on PATH Fix: {CLAUDE_FIX}",
                id="claude-absent",
            ),
            pytest.param({}, {}, 4, "ok      gh: logged in", id="gh-logged-in"),
            pytest.param(
                {},
                {"gh": ProbeResult(1, b"", is_timed_out=False)},
                4,
                "missing gh: gh auth status exited 1 Fix: gh auth login",
                id="gh-exit-one",
            ),
            pytest.param(
                {},
                {"gh": TIMED_OUT},
                4,
                "missing gh: timed out after 10 s Fix: gh auth login",
                id="gh-timeout",
            ),
            pytest.param(
                {"gh": None}, {}, 4, f"missing gh: not on PATH Fix: {GH_FIX}", id="gh-absent"
            ),
        ],
    )
    def test_prints_tool_line_when_probe_answers(
        self,
        demo_workspace: Workspace,
        install_probe: ProbeInstaller,
        *,
        run_setup: SetupRunner,
        monkeypatch: pytest.MonkeyPatch,
        paths: Mapping[str, str | None],
        results: Mapping[str, ProbeResult],
        position: int,
        line: str,
    ) -> None:
        monkeypatch.setenv(KEY_VARIABLE, SYNTHETIC_KEY)
        install_probe(paths, results)
        expected = [*TOOL_LINES_OK, TRACKER_OK]
        expected[position] = line

        result = run_setup(demo_workspace.hub)

        assert result.stdout.splitlines()[:6] == expected
        assert result.exit_code == (0 if line.startswith("ok") else 1)

    @pytest.mark.parametrize(
        ("key", "line"),
        [(None, TRACKER_NO_KEY), ("", TRACKER_NO_KEY), (SYNTHETIC_KEY, TRACKER_OK)],
        ids=["unset", "empty", "synthetic"],
    )
    def test_prints_tracker_line_when_tools_key_varies(
        self,
        demo_workspace: Workspace,
        install_probe: ProbeInstaller,
        *,
        run_setup: SetupRunner,
        monkeypatch: pytest.MonkeyPatch,
        key: str | None,
        line: str,
    ) -> None:
        if key is None:
            monkeypatch.delenv(KEY_VARIABLE, raising=False)
        else:
            monkeypatch.setenv(KEY_VARIABLE, key)
        install_probe()

        result = run_setup(demo_workspace.hub)

        assert result.stdout.splitlines()[5] == line
        assert SYNTHETIC_KEY.encode() not in result.stdout_bytes
        assert SYNTHETIC_KEY.encode() not in result.stderr_bytes

    @pytest.mark.parametrize(
        ("claude", "line"),
        [(TOOL_PATHS["claude"], TRACKER_MCP_OK), (None, TRACKER_MCP_NO_CLAUDE)],
        ids=["claude-present", "claude-absent"],
    )
    def test_reads_transport_from_local_file_when_tools_see_mcp(
        self,
        demo_workspace: Workspace,
        install_probe: ProbeInstaller,
        *,
        run_setup: SetupRunner,
        monkeypatch: pytest.MonkeyPatch,
        claude: str | None,
        line: str,
    ) -> None:
        # No key: transport mcp does not need one.
        monkeypatch.delenv(KEY_VARIABLE, raising=False)
        demo_workspace.write_local('{"tracker": {"transport": "mcp"}}\n')
        install_probe({"claude": claude})

        result = run_setup(demo_workspace.hub)

        assert result.stdout.splitlines()[5] == line

    def test_uses_hub_transport_when_tools_see_invalid_local_file(
        self,
        demo_workspace: Workspace,
        install_probe: ProbeInstaller,
        *,
        run_setup: SetupRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The file asks for mcp but is invalid: hub.json's transport (api) is the one checked.
        monkeypatch.delenv(KEY_VARIABLE, raising=False)
        demo_workspace.write_local('{"tracker": {"transport": "mcp"}, "repos": []}\n')
        install_probe()

        result = run_setup(demo_workspace.hub)

        assert result.stdout.splitlines()[5] == TRACKER_NO_KEY

    def test_bounds_every_probe_when_tools_run(
        self, demo_workspace: Workspace, tools_ok: FakeToolProbe, run_setup: SetupRunner
    ) -> None:
        result = run_setup(demo_workspace.hub)

        assert result.exit_code == 0, result.output
        assert [argv for argv, _ in tools_ok.runs] == [
            (TOOL_PATHS["uv"], "--version"),
            (TOOL_PATHS["python3"], "--version"),
            (TOOL_PATHS["gh"], "auth", "status"),
        ]
        assert all(0 < timeout <= 10 for _, timeout in tools_ok.runs)

    def test_hides_tracker_key_from_tools_when_real_probe_runs(
        self,
        demo_workspace: Workspace,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        bin_dir = tmp_path / "tools-bin"
        bin_dir.mkdir()
        log_path = tmp_path / "tools.log"
        _write_tool(bin_dir, "uv", log_path=log_path, output="uv 0.9.5 (abc 2025-09-30)")
        _write_tool(bin_dir, "python3", log_path=log_path, output="Python 3.12.4")
        _write_tool(bin_dir, "gh", log_path=log_path, output="Logged in")
        _write_tool(bin_dir, "claude", log_path=log_path, output="claude")
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv(KEY_VARIABLE, SYNTHETIC_KEY)

        result = run_setup(demo_workspace.hub)

        assert result.stdout.splitlines()[:6] == [*TOOL_LINES_OK, TRACKER_OK]
        # Each tool ran once (claude is only looked up), none with the key in its environment.
        assert log_path.read_text(encoding="utf-8").splitlines() == ["uv:", "python3:", "gh:"]
        assert SYNTHETIC_KEY.encode() not in result.stdout_bytes
        assert SYNTHETIC_KEY.encode() not in result.stderr_bytes
