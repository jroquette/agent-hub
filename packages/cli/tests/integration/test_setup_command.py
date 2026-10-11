"""``hub setup``: one-command onboarding of a developer's machine (AGH-71).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``) whose git is
``env_traced_git``: each call is logged with its environment, then the real git runs. The tests
replace only the command's seams: the tool probe (``setup_tools.tool_probe``), the terminal
check of the prompt (``setup_identity.stdin_is_tty``) and the network timeout
(``setup_repos.NETWORK_TIMEOUT_SECONDS``).
"""

import errno
import json
import os
import re
import shlex
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli import exclusive_write, setup_identity, setup_tools
from agent_hub.cli.exclusive_write import TEMP_INFIX
from agent_hub.cli.main import app
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.workspace.setup_checklist import (
    CLAUDE_FIX,
    GH_FIX,
    GIT_FIX,
    IDENTITY_FILE_FIX,
    INVALID_LOCAL_FIX,
    PREFIX_FIX,
    PYTHON_FIX,
    RERUN_FIX,
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


# The developer the team-hub tests give git; AC-71.7's exact file.
JANE = ("Jane Roe", "jane@example.com")
LOCAL_BYTES = (
    b'{\n  "project": {\n    "branch_prefix": "jane/",\n    "author_name": "Jane Roe",\n'
    b'    "author_email": "jane@example.com"\n  }\n}\n'
)
WROTE_LINE = (
    "ok      identity: wrote hub.local.json: jane/, Jane Roe <jane@example.com> (git config)"
)
DECLINED_LINE = f"missing identity: hub.local.json not written (declined) Fix: {IDENTITY_FILE_FIX}"
NO_TERMINAL_LINE = (
    "missing identity: hub.local.json not written (stdin is not a terminal)"
    f" Fix: {IDENTITY_FILE_FIX}"
)
GIT_LACKS_LINES = {
    "email": "missing identity: git config in the hub has no user.email"
    " Fix: git config user.email <you@example.com>, then ./hub setup",
    "name": "missing identity: git config in the hub has no user.name"
    ' Fix: git config user.name "<Your Name>", then ./hub setup',
    "both": "missing identity: git config in the hub has no user.name or user.email"
    ' Fix: git config user.name "<Your Name>" and git config user.email <you@example.com>,'
    " then ./hub setup",
}
LOCAL_FILE = "hub.local.json"
_IDENTITY_LINE = re.compile(r"^(ok|missing) +identity: ")
_SUB_LINE = " " * 8


def _identity_lines(stdout: str) -> list[str]:
    """The ``identity`` line and its sub-lines."""
    lines = stdout.splitlines()
    start = next(index for index, line in enumerate(lines) if _IDENTITY_LINE.match(line))
    end = start + 1
    while end < len(lines) and lines[end].startswith(_SUB_LINE):
        end += 1
    return lines[start:end]


def _team_hub(workspace: Workspace, *, git: tuple[str, str] | None = JANE) -> Path:
    """The workspace hub without an identity in ``hub.json``; git gives ``git`` when set."""
    workspace.drop_identity()
    if git is not None:
        workspace.git_identity(*git)
    return Path(workspace.hub)


def _git_user(workspace: Workspace, monkeypatch: pytest.MonkeyPatch, **user: str) -> None:
    """Give the command's git only the ``user`` keys given (``name``, ``email``)."""
    config = Path(workspace.base) / "partial.gitconfig"
    entries = "".join(f"\t{key} = {value}\n" for key, value in user.items())
    config.write_text(f"[user]\n{entries}", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


def _proposal(home: Path, text: str) -> str:
    return f"hub setup: proposed hub.local.json in {os.path.realpath(home)}: {text}\n"


def _prompt(home: Path) -> str:
    return f"Write {os.path.realpath(home)}/hub.local.json? [y/N] "


def _temp_names(folder: Path) -> list[str]:
    return [name for name in os.listdir(folder) if TEMP_INFIX in name]


def _snapshot(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


@pytest.mark.usefixtures("tools_ok")
class TestIdentity:
    def test_reads_identity_from_hub_json_when_all_keys_set(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        result = run_setup(demo_workspace.hub)

        assert _identity_lines(result.stdout) == [
            "ok      identity: jdoe/, Jane Doe <jane@example.com> (hub.json)"
        ]
        assert not (demo_workspace.hub / LOCAL_FILE).exists()
        assert [call.args for call in env_traced_git.calls() if "user." in call.args] == []
        assert result.stderr == ""
        assert result.exit_code == 0, result.output

    def test_keeps_existing_local_when_file_valid(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        demo_workspace.write_local('{"project": {"branch_prefix": "jr/"}}\n')
        before = _snapshot(hub / LOCAL_FILE)

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            "ok      identity: jr/, Jane Roe <jane@example.com> (hub.local.json, git config)"
        ]
        assert _snapshot(hub / LOCAL_FILE) == before
        assert result.stderr == ""
        assert result.exit_code == 0, result.output

    def test_keeps_existing_local_when_file_invalid(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        demo_workspace.write_local('{"repos": []}\n')
        before = _snapshot(hub / LOCAL_FILE)

        result = run_setup(hub, "--yes")

        lines = _identity_lines(result.stdout)
        assert lines[0] == f"missing identity: hub.local.json is invalid Fix: {INVALID_LOCAL_FIX}"
        assert len(lines) > 1
        assert all(line.startswith(f"{_SUB_LINE}hub.local.json: ") for line in lines[1:])
        assert _snapshot(hub / LOCAL_FILE) == before
        assert result.exit_code == 1

    @pytest.mark.parametrize(
        ("user", "lacking"),
        [({"name": "Jane Roe"}, "email"), ({"email": "jane@example.com"}, "name"), ({}, "both")],
        ids=["email", "name", "both"],
    )
    def test_writes_nothing_when_git_lacks_email(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        user: dict[str, str],
        lacking: str,
    ) -> None:
        hub = _team_hub(demo_workspace, git=None)
        _git_user(demo_workspace, monkeypatch, **user)

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [GIT_LACKS_LINES[lacking]]
        assert not (hub / LOCAL_FILE).exists()
        assert _temp_names(hub) == []
        assert result.stderr == ""
        assert result.exit_code == 1

    @pytest.mark.parametrize(
        ("source", "giver"),
        [("git", "git's user.email"), ("hub-json", "hub.json's project.author_email")],
    )
    def test_writes_nothing_when_git_lacks_valid_prefix(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        source: str,
        giver: str,
    ) -> None:
        hub = _team_hub(demo_workspace, git=("Jane Roe", "j+x@example.com"))
        if source == "hub-json":
            # hub.json's email wins over git's: the derived prefix follows it (E10).
            demo_workspace.git_identity(*JANE)
            _edit_hub_json(
                hub,
                lambda document: document["project"].update(
                    author_name="Jane Roe", author_email="j+x@example.com"
                ),
            )

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            f'missing identity: {giver} gives "j+x", not a valid branch prefix Fix: {PREFIX_FIX}'
        ]
        assert not (hub / LOCAL_FILE).exists()
        assert result.stderr == ""
        assert result.exit_code == 1

    def test_names_git_problem_when_git_lacks_answer(
        self,
        demo_workspace: Workspace,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        hub = _team_hub(demo_workspace)
        # The fake probe answers for the tools; git is on no PATH folder.
        no_git = tmp_path / "no-git-bin"
        no_git.mkdir()
        monkeypatch.setenv("PATH", str(no_git))

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            GIT_LACKS_LINES["both"],
            f"{_SUB_LINE}git: git not found",
        ]
        assert not (hub / LOCAL_FILE).exists()
        assert result.exit_code == 1

    def test_reports_no_prefix_when_local_file_sets_unusable_email(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        demo_workspace.write_local(
            '{"project": {"author_name": "Jane Roe", "author_email": "j+x@example.com"}}\n'
        )
        before = _snapshot(hub / LOCAL_FILE)

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            f"missing identity: no branch prefix Fix: {PREFIX_FIX}",
            f"{_SUB_LINE}no branch prefix for this developer; set one of:",
            f"{_SUB_LINE}  hub.local.json → project.branch_prefix",
            f"{_SUB_LINE}  hub.json → project.branch_prefix",
            f"{_SUB_LINE}  git config user.email in the hub (its local part plus /)",
            f'{_SUB_LINE}  hub.local.json\'s project.author_email gives "j+x", not a valid prefix',
        ]
        assert _snapshot(hub / LOCAL_FILE) == before
        assert result.exit_code == 1

    def test_names_git_gap_when_local_file_sets_prefix_only(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hub = _team_hub(demo_workspace, git=None)
        _git_user(demo_workspace, monkeypatch, name="Jane Roe")
        demo_workspace.write_local('{"project": {"branch_prefix": "jr/"}}\n')

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [GIT_LACKS_LINES["email"]]
        assert result.exit_code == 1


@pytest.mark.usefixtures("tools_ok")
class TestWritesLocal:
    @pytest.mark.parametrize("umask", [0o077, 0o022], ids=["umask-077", "umask-022"])
    def test_writes_local_file_when_team_hub_runs_with_yes(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        set_umask: Callable[[int], None],
        umask: int,
    ) -> None:
        hub = _team_hub(demo_workspace)
        set_umask(umask)

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [WROTE_LINE]
        assert (hub / LOCAL_FILE).read_bytes() == LOCAL_BYTES
        assert stat.S_IMODE((hub / LOCAL_FILE).stat().st_mode) == 0o644
        assert _temp_names(hub) == []
        assert result.stderr == _proposal(hub, "jane/, Jane Roe <jane@example.com> (git config)")
        assert result.exit_code == 0, result.output

    def test_writes_local_only_unset_keys_when_hub_sets_prefix(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        _edit_hub_json(hub, lambda document: document["project"].update(branch_prefix="me/"))

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            "ok      identity: wrote hub.local.json: Jane Roe <jane@example.com> (git config)"
        ]
        assert json.loads((hub / LOCAL_FILE).read_bytes()) == {
            "project": {"author_name": "Jane Roe", "author_email": "jane@example.com"}
        }
        assert result.exit_code == 0, result.output

    def test_writes_local_in_main_checkout_when_run_from_hub_worktree(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        demo_workspace.init_hub_repo(None)
        # Next to the hub, so the worktree's parent is the hub's (E12).
        worktree = Path(demo_workspace.ws) / "hub-worktree"
        demo_workspace.git(hub, "worktree", "add", "-q", str(worktree))

        result = run_setup(worktree, "--yes")

        assert _identity_lines(result.stdout) == [WROTE_LINE]
        assert (hub / LOCAL_FILE).read_bytes() == LOCAL_BYTES
        assert not (worktree / LOCAL_FILE).exists()
        assert result.exit_code == 0, result.output

    def test_leaves_appeared_file_when_writes_local_races(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hub = _team_hub(demo_workspace)
        appeared = b'{"project": {"branch_prefix": "other/"}}\n'
        real_link = os.link

        def appear_then_link(source: Path, target: Path) -> None:
            Path(target).write_bytes(appeared)
            real_link(source, target)

        monkeypatch.setattr(exclusive_write.os, "link", appear_then_link)

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            f"missing identity: hub.local.json appeared while writing; left as is Fix: {RERUN_FIX}"
        ]
        assert (hub / LOCAL_FILE).read_bytes() == appeared
        assert _temp_names(hub) == []
        assert result.exit_code == 1

    @pytest.mark.parametrize("case", ["link-denied", "temp-taken"])
    def test_reports_write_error_when_writes_local_cannot_link(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
    ) -> None:
        hub = _team_hub(demo_workspace)
        if case == "link-denied":
            code = errno.EACCES

            def refuse_link(source: Path, target: Path) -> None:
                raise PermissionError(code, os.strerror(code), str(source), None, str(target))

            monkeypatch.setattr(exclusive_write.os, "link", refuse_link)
        else:
            # The temp name is taken before the open: write_exclusive raises FileExistsError.
            code = errno.EEXIST
            monkeypatch.setattr(exclusive_write.secrets, "token_hex", lambda _size: "0" * 8)
            (hub / f".{LOCAL_FILE}{TEMP_INFIX}{'0' * 8}").write_bytes(b"")

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            f"missing identity: could not write hub.local.json: {os.strerror(code)}"
            f" Fix: {IDENTITY_FILE_FIX}"
        ]
        # Only the reason: the error's own text names the paths.
        assert os.path.realpath(hub) not in result.stdout
        assert not (hub / LOCAL_FILE).exists()
        assert result.exit_code == 1


@pytest.mark.usefixtures("tools_ok")
class TestPrompt:
    @pytest.mark.parametrize("answer", ["y\n", "YES\n", " yes \n"], ids=["y", "YES", "spaced"])
    def test_writes_file_when_prompt_answered_yes(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        answer: str,
    ) -> None:
        hub = _team_hub(demo_workspace)
        monkeypatch.setattr(setup_identity, "stdin_is_tty", lambda: True)

        result = run_setup(hub, input=answer)

        assert _identity_lines(result.stdout) == [WROTE_LINE]
        assert (hub / LOCAL_FILE).read_bytes() == LOCAL_BYTES
        assert result.stderr == _proposal(
            hub, "jane/, Jane Roe <jane@example.com> (git config)"
        ) + _prompt(hub)
        assert "proposed" not in result.stdout
        assert "[y/N]" not in result.stdout
        assert result.exit_code == 0, result.output

    @pytest.mark.parametrize(
        "answer", ["n\n", "\n", "", "y" * 100 + "\n"], ids=["n", "empty", "eof", "long"]
    )
    def test_writes_nothing_when_prompt_declined(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        answer: str,
    ) -> None:
        hub = _team_hub(demo_workspace)
        monkeypatch.setattr(setup_identity, "stdin_is_tty", lambda: True)

        result = run_setup(hub, input=answer)

        assert _identity_lines(result.stdout) == [DECLINED_LINE]
        assert not (hub / LOCAL_FILE).exists()
        assert result.stderr.endswith(_prompt(hub))
        assert result.exit_code == 1

    def test_writes_nothing_when_prompt_has_no_terminal(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)

        result = run_setup(hub, input="y\n")

        assert _identity_lines(result.stdout) == [NO_TERMINAL_LINE]
        assert not (hub / LOCAL_FILE).exists()
        assert result.stderr == _proposal(hub, "jane/, Jane Roe <jane@example.com> (git config)")
        assert result.exit_code == 1
