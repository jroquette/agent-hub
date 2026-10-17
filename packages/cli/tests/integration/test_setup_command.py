"""``hub setup``: one-command onboarding of a developer's machine (AGH-71).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``) whose git is
``env_traced_git``: each call is logged with its environment, then the real git runs. The tests
replace only the command's seams: the tool probe (``setup_tools.tool_probe``), the terminal
check of the prompt (``setup_identity.stdin_is_tty``) and the timeouts
(``setup_repos.NETWORK_TIMEOUT_SECONDS``, ``setup_repos.CHECK_TIMEOUT_SECONDS``,
``setup_identity.PROBE_TIMEOUT_SECONDS``).
"""

import errno
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli import exclusive_write, setup_identity, setup_repos, setup_tools
from agent_hub.cli.exclusive_write import TEMP_INFIX
from agent_hub.cli.main import app
from agent_hub.cli.setup_identity import ANSWER_LIMIT
from agent_hub.core.hub_config.local_config import LOCAL_FILE_MAX_BYTES
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.workspace.setup_checklist import (
    CLAUDE_FIX,
    CLONE_FIX,
    DOCTOR_FIX,
    FETCH_FIX,
    GH_FIX,
    GIT_FIX,
    GITIGNORE_FIX,
    IDENTITY_FILE_FIX,
    INVALID_LOCAL_FIX,
    MOVE_AWAY_FIX,
    PREFIX_FIX,
    PYTHON_FIX,
    RERUN_FIX,
    STATUS_FIX,
    TRACKER_KEY_FIX,
    UV_FIX,
    ProbeResult,
)

# The conftest's fixtures (tests cannot import a conftest in importlib mode).
type Workspace = Any
type TracedGit = Any
type SetupRunner = Callable[..., Result]
type TreeDigest = Callable[[Path], dict[str, Any]]

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

    def run(root: Path, *args: str, input: str | bytes | None = None) -> Result:
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


_SUMMARY_LINE = re.compile(r"^setup: ")
ITEM_ORDER = [
    "uv",
    "git",
    "python3",
    "claude",
    "gh",
    "tracker",
    "identity",
    "repo demo-api",
    "repo demo-web",
    "hub doctor",
]


def _items(stdout: str) -> list[str]:
    """The item names of the checklist lines, sub-lines and totals left out."""
    return [
        line[8:].split(":", 1)[0]
        for line in stdout.splitlines()
        if not line.startswith(_SUB_LINE) and not _SUMMARY_LINE.match(line)
    ]


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

    def test_exits_zero_when_everything_set_up(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        tools_ok: FakeToolProbe,
    ) -> None:
        result = run_setup(demo_workspace.hub)

        assert _items(result.stdout) == ITEM_ORDER
        assert result.stdout.splitlines()[-1] == "setup: 10 ok"
        assert result.exit_code == 0, result.output

    def test_exits_one_after_full_checklist_when_item_missing(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        install_probe: ProbeInstaller,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(KEY_VARIABLE, SYNTHETIC_KEY)
        install_probe(paths={"gh": None})

        result = run_setup(demo_workspace.hub)

        assert _items(result.stdout) == ITEM_ORDER
        assert f"missing gh: not on PATH Fix: {GH_FIX}" in result.stdout.splitlines()
        assert result.stdout.splitlines()[-1] == "setup: 1 missing, 9 ok"
        assert result.exit_code == 1


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
        demo_workspace.write_local('{"tracker": {"transport": "mcp"}, "doctor": {}}\n')
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


def _identity_reads(traced: TracedGit) -> list[str]:
    """The logged reads of git's ``user.name`` and ``user.email``, in order."""
    return [call.args for call in traced.calls() if call.args.startswith("config --get user.")]


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
        demo_workspace.write_local('{"doctor": {}}\n')
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

    @pytest.mark.parametrize(
        "local", [None, '{"project": {"branch_prefix": "jr/"}}\n'], ids=["no-local", "prefix-only"]
    )
    def test_names_rejected_email_when_git_email_not_an_address(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        local: str | None,
    ) -> None:
        hub = _team_hub(demo_workspace, git=None)
        _git_user(demo_workspace, monkeypatch, name="Jane Roe", email="jane at example")
        if local is not None:
            demo_workspace.write_local(local)

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            "missing identity: git's user.email is not an email address"
            " Fix: git config user.email <you@example.com>, then ./hub setup"
        ]
        # Git's value is never repeated.
        assert "jane at example" not in result.output
        assert (hub / LOCAL_FILE).exists() is (local is not None)
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
        assert _identity_reads(env_traced_git) == [
            "config --get user.name",
            "config --get user.email",
        ]
        assert result.exit_code == 0, result.output

    def test_reads_no_git_email_when_hub_sets_email(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        _edit_hub_json(
            hub, lambda document: document["project"].update(author_email="jr@example.com")
        )

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            "ok      identity: wrote hub.local.json: jr/, Jane Roe (hub.json, git config)"
        ]
        assert _identity_reads(env_traced_git) == ["config --get user.name"]
        assert result.exit_code == 0, result.output

    def test_writes_nothing_when_writes_local_exceeds_file_limit(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hub = _team_hub(demo_workspace, git=None)
        # One byte over the limit the reader keeps: AC-71.7's file with a longer name.
        name = "J" * (LOCAL_FILE_MAX_BYTES + 1 - len(LOCAL_BYTES) + len(JANE[0]))
        _git_user(demo_workspace, monkeypatch, name=name, email=JANE[1])

        result = run_setup(hub, "--yes")

        assert _identity_lines(result.stdout) == [
            f"missing identity: hub.local.json not written (larger than {LOCAL_FILE_MAX_BYTES}"
            " bytes) Fix: shorten git's user.name or user.email in the hub, then ./hub setup"
        ]
        assert not (hub / LOCAL_FILE).exists()
        assert _temp_names(hub) == []
        assert result.stderr == ""
        assert result.exit_code == 1

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
    @pytest.mark.parametrize(
        "answer",
        ["y\n", "YES\n", " yes \n", "y" + " " * (ANSWER_LIMIT - 2) + "\n"],
        ids=["y", "YES", "spaced", "at-limit"],
    )
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
        "answer",
        [
            "n\n",
            "\n",
            "",
            "y" * 100 + "\n",
            "y" + " " * ANSWER_LIMIT + "\n",
            b"\xff\n",
            b"y\xff\n",
        ],
        ids=["n", "empty", "eof", "long", "y-past-limit", "not-utf8", "y-not-utf8"],
    )
    def test_writes_nothing_when_prompt_declined(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        answer: str | bytes,
    ) -> None:
        hub = _team_hub(demo_workspace)
        monkeypatch.setattr(setup_identity, "stdin_is_tty", lambda: True)

        result = run_setup(hub, input=answer)

        assert result.exception is None or isinstance(result.exception, SystemExit)
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


GITIGNORE_LINE = f"missing gitignore: hub.local.json is not ignored by git Fix: {GITIGNORE_FIX}"


def _unignore_local_file(hub: Path) -> bytes:
    """Drop the ``hub.local.json`` line from the hub's ``.gitignore``; its new bytes."""
    path = hub / ".gitignore"
    kept = [line for line in path.read_text(encoding="utf-8").splitlines() if line != LOCAL_FILE]
    path.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
    return path.read_bytes()


def _check_ignore_calls(traced: TracedGit) -> list[Any]:
    return [call for call in traced.calls() if " check-ignore " in f" {call.args} "]


def _hang_check_ignore(traced: TracedGit, folder: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put first on ``PATH`` a ``git`` whose ``check-ignore`` never answers (it logs its pid,
    then becomes ``sleep 30``); every other call goes on to the traced git. The pid log."""
    bin_dir = folder / "hanging-check-ignore-bin"
    bin_dir.mkdir()
    pid_log = folder / "hanging-check-ignore.pids"
    script = bin_dir / "git"
    script.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        f'  *" check-ignore "*) echo "$$" >> {shlex.quote(str(pid_log))}; exec sleep 30 ;;\n'
        "esac\n"
        f'exec {shlex.quote(str(traced.bin_dir / "git"))} "$@"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return pid_log


@pytest.mark.usefixtures("tools_ok")
class TestGitignore:
    def test_reports_gitignore_when_local_file_not_ignored(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        ignore_bytes = _unignore_local_file(hub)
        demo_workspace.init_hub_repo(None)

        result = run_setup(hub, "--yes")

        lines = result.stdout.splitlines()
        assert lines[lines.index(WROTE_LINE) + 1] == GITIGNORE_LINE
        assert (hub / ".gitignore").read_bytes() == ignore_bytes
        assert (hub / LOCAL_FILE).read_bytes() == LOCAL_BYTES
        # Setup's own git env (E3): no prompt, no tracker key, though the command has one.
        calls = _check_ignore_calls(env_traced_git)
        assert [(call.args, call.prompt, call.has_key) for call in calls] == [
            (f"-C {os.path.realpath(hub)} check-ignore -q {LOCAL_FILE}", "0", False)
        ]
        assert result.exit_code == 1

    def test_prints_no_gitignore_line_when_local_file_ignored(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        demo_workspace.init_hub_repo(None)

        result = run_setup(hub, "--yes")

        assert WROTE_LINE in result.stdout.splitlines()
        assert "gitignore" not in result.stdout
        assert len(_check_ignore_calls(env_traced_git)) == 1
        assert result.exit_code == 0, result.output

    def test_prints_no_gitignore_line_when_hub_not_a_repository(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        ignore_bytes = _unignore_local_file(hub)

        result = run_setup(hub, "--yes")

        assert WROTE_LINE in result.stdout.splitlines()
        assert "gitignore" not in result.stdout
        # Asked once: git's own answer (no repository) is what gives no line.
        assert len(_check_ignore_calls(env_traced_git)) == 1
        assert (hub / ".gitignore").read_bytes() == ignore_bytes
        assert result.exit_code == 0, result.output

    def test_names_tracked_file_fix_when_local_file_tracked(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = _team_hub(demo_workspace)
        demo_workspace.write_local(LOCAL_BYTES.decode("utf-8"))
        demo_workspace.init_hub_repo(None)
        demo_workspace.git(hub, "add", "-f", LOCAL_FILE)
        demo_workspace.git(hub, "commit", "-q", "-m", "track the local file")
        ignore_bytes = (hub / ".gitignore").read_bytes()

        result = run_setup(hub)

        # .gitignore lists the file, yet git tracks it, so git does not ignore it.
        assert LOCAL_FILE in ignore_bytes.decode("utf-8").splitlines()
        assert [line for line in result.stdout.splitlines() if " gitignore: " in line] == [
            "missing gitignore: hub.local.json is not ignored by git"
            " Fix: add the line hub.local.json to .gitignore and commit it;"
            " if git tracks it, also git rm --cached hub.local.json"
        ]
        assert (hub / ".gitignore").read_bytes() == ignore_bytes
        assert (hub / LOCAL_FILE).read_bytes() == LOCAL_BYTES
        assert result.exit_code == 1

    def test_prints_no_gitignore_line_when_git_not_on_path(
        self,
        demo_workspace: Workspace,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        hub = _team_hub(demo_workspace)
        demo_workspace.write_local(LOCAL_BYTES.decode("utf-8"))
        _unignore_local_file(hub)
        demo_workspace.init_hub_repo(None)
        # The fake probe answers for the tools; git is on no PATH folder.
        no_git = tmp_path / "no-git-bin"
        no_git.mkdir()
        monkeypatch.setenv("PATH", str(no_git))

        result = run_setup(hub)

        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert _identity_lines(result.stdout) == [
            "ok      identity: jane/, Jane Roe <jane@example.com> (hub.local.json)"
        ]
        assert "gitignore" not in result.stdout
        # Only the repos, which need git too, are missing.
        # Doctor cannot list the files without git either: an error of its own.
        assert _doctor_lines(result.stdout)[1].endswith(NO_GIT_FINDING_END)
        assert result.stdout.splitlines()[-1] == "setup: 3 missing, 7 ok"
        assert result.exit_code == 1

    def test_prints_no_gitignore_line_when_check_ignore_hangs(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        hub = _team_hub(demo_workspace)
        _unignore_local_file(hub)
        demo_workspace.init_hub_repo(None)
        pid_log = _hang_check_ignore(env_traced_git, tmp_path, monkeypatch)
        monkeypatch.setattr(setup_identity, "PROBE_TIMEOUT_SECONDS", 0.5)
        bounds: list[tuple[object, object]] = []
        real_run_child = setup_identity.run_child

        def recording_run_child(argv: Sequence[str], **options: Any) -> Any:
            bounds.append((options.get("timeout"), options.get("output_limit")))
            return real_run_child(argv, **options)

        monkeypatch.setattr(setup_identity, "run_child", recording_run_child)

        result = run_setup(hub, "--yes")

        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert WROTE_LINE in result.stdout.splitlines()
        assert "gitignore" not in result.stdout
        # Bounded in time and in the output kept, as setup's other git calls.
        assert bounds == [(0.5, setup_repos.OUTPUT_LIMIT)]
        pids = [int(line) for line in pid_log.read_text(encoding="utf-8").split()]
        assert len(pids) == 1
        with pytest.raises(ProcessLookupError):
            os.kill(pids[0], 0)
        assert result.exit_code == 0, result.output

    def test_prints_no_gitignore_line_when_no_local_file(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = Path(demo_workspace.hub)
        _unignore_local_file(hub)
        demo_workspace.init_hub_repo(None)

        result = run_setup(hub)

        # Q-2: hub.json sets the identity, so no file is written and nothing is checked.
        assert not (hub / LOCAL_FILE).exists()
        assert "gitignore" not in result.stdout
        assert _check_ignore_calls(env_traced_git) == []
        assert result.exit_code == 0, result.output


_REPO_LINE = re.compile(r"^(ok|missing) +repo ")
SYNTHETIC_TOKEN = "ghs" + "_" + "t0k" * 8


def _repo_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if _REPO_LINE.match(line)]


def _network_calls(traced: TracedGit) -> list[Any]:
    """The logged clones and fetches, in order."""
    return [
        call
        for call in traced.calls()
        if call.args.startswith("clone ") or " fetch " in f" {call.args} "
    ]


def _ws(workspace: Workspace) -> str:
    return os.path.realpath(workspace.ws)


def _remove_repo(workspace: Workspace, repo: str) -> None:
    shutil.rmtree(Path(workspace.ws) / repo)


def _mtimes(root: Path) -> dict[str, int]:
    """Each entry's modification time under ``root`` (itself as ``.``), links not followed."""
    found = {".": root.lstat().st_mtime_ns}
    if root.is_dir() and not root.is_symlink():
        for folder, folders, files in os.walk(root):
            for name in [*folders, *files]:
                path = Path(folder) / name
                found[path.relative_to(root).as_posix()] = path.lstat().st_mtime_ns
    return found


def _repo_with_origin(workspace: Workspace, folder: Path) -> None:
    """Make ``folder`` a repo with one commit and an ``origin``: what a fetch could reach."""
    workspace.git(folder, "init", "-q", "-b", "trunk")
    workspace.git(folder, "commit", "-q", "--allow-empty", "-m", "outer")
    workspace.git(folder, "remote", "add", "origin", str(workspace.origin("demo-api")))


def _hang_head_read(traced: TracedGit, folder: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put first on ``PATH`` a ``git`` whose commit check in ``demo-api`` never answers (it
    logs its pid, then becomes ``sleep 30``); every other call goes on to the traced git (which
    logs it). The pid log."""
    bin_dir = folder / "hanging-head-read-bin"
    bin_dir.mkdir()
    pid_log = folder / "hanging-head-read.pids"
    script = bin_dir / "git"
    script.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        f'  *"/demo-api rev-parse --verify -q HEAD "*) echo "$$" >> {shlex.quote(str(pid_log))};'
        " exec sleep 30 ;;\n"
        "esac\n"
        f'exec {shlex.quote(str(traced.bin_dir / "git"))} "$@"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return pid_log


def _cloned_line(repo: str, scheme: str) -> str:
    return f"ok      repo {repo}: cloned acme/{repo} into ../{repo} ({scheme})"


def _clone_fix(repo: str) -> str:
    return CLONE_FIX.format(github=f"acme/{repo}")


@pytest.mark.usefixtures("tools_ok")
class TestRepos:
    def test_clones_missing_and_fetches_present_when_repos_listed(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        demo_workspace.rewrite_github()
        _remove_repo(demo_workspace, "demo-web")
        ws = _ws(demo_workspace)

        result = run_setup(demo_workspace.hub, "--yes")

        assert [call.args for call in _network_calls(env_traced_git)] == [
            f"-C {ws}/demo-api fetch --quiet origin",
            f"clone --quiet https://github.com/acme/demo-web.git {ws}/demo-web",
        ]
        assert _repo_lines(result.stdout) == [
            "ok      repo demo-api: present, fetched",
            _cloned_line("demo-web", "https"),
        ]
        assert (Path(demo_workspace.ws) / "demo-web" / ".git").is_dir()
        assert result.stdout.splitlines()[-1] == "setup: 10 ok"
        assert result.exit_code == 0, result.output

    def test_sets_no_prompt_and_drops_location_and_key_when_setup_git_runs(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        demo_workspace.rewrite_github()
        demo_workspace.init_hub_repo(None)
        _remove_repo(demo_workspace, "demo-web")
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
        assert os.environ[KEY_VARIABLE] == SYNTHETIC_KEY
        hub = os.path.realpath(demo_workspace.hub)
        ws = _ws(demo_workspace)

        result = run_setup(demo_workspace.hub, "--yes")

        calls = env_traced_git.calls()
        assert [call.args for call in calls if call.has_git_dir] == []
        own = [
            call
            for call in calls
            if call.args.startswith(("clone ", "config --get remote.origin.url"))
            or call.args.startswith((f"-C {ws}/", f"-C {hub} check-ignore"))
        ]
        assert [(call.args, call.prompt, call.has_key) for call in own] == [
            ("config --get remote.origin.url", "0", False),
            (f"-C {ws}/demo-api rev-parse --verify -q HEAD", "0", False),
            (f"-C {ws}/demo-api fetch --quiet origin", "0", False),
            (f"clone --quiet https://github.com/acme/demo-web.git {ws}/demo-web", "0", False),
        ]
        assert result.exit_code == 0, result.output

    @pytest.mark.parametrize(
        "entry",
        [
            "folder-with-file",
            "regular-file",
            "dangling-link",
            "empty-git-folder",
            "linked-empty-git-folder",
        ],
    )
    def test_leaves_entry_untouched_when_not_a_repository(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        tree_digest: TreeDigest,
        entry: str,
    ) -> None:
        ws = Path(demo_workspace.ws)
        path = ws / "demo-api"
        shutil.rmtree(path)
        checks: list[str] = []
        check = f"-C {_ws(demo_workspace)}/demo-api rev-parse --verify -q HEAD"
        # The repo git must never reach through ``../demo-api``, and its refs before the run.
        guarded = ws
        if entry == "folder-with-file":
            path.mkdir()
            (path / "notes.txt").write_bytes(b"mine\n")
        elif entry == "regular-file":
            path.write_bytes(b"mine\n")
        elif entry == "dangling-link":
            path.symlink_to(Path(demo_workspace.base) / "nowhere")
        elif entry == "empty-git-folder":
            # A ``.git`` folder git cannot read, in a workspace that is itself a repo with an
            # origin: git must not search upwards and fetch into the workspace's repo (E28).
            (path / ".git").mkdir(parents=True)
            _repo_with_origin(demo_workspace, ws)
            checks = [check]
        else:
            # The same ``.git`` folder through a link, in a repo outside the workspace: the
            # ceiling must hold at the link's target too, not only at the workspace (E30).
            guarded = Path(demo_workspace.base) / "outer"
            target = guarded / "sub" / "demo"
            (target / ".git").mkdir(parents=True)
            _repo_with_origin(demo_workspace, guarded)
            path.symlink_to(target)
            checks = [check]
        refs = demo_workspace.git(guarded, "for-each-ref") if checks else ""
        before = (tree_digest(path), _mtimes(path))

        result = run_setup(demo_workspace.hub, "--yes")

        assert (tree_digest(path), _mtimes(path)) == before
        if checks:
            # Git refuses the empty ``.git`` (exit 128): it never reads the repo around it.
            first = (
                "missing repo demo-api: git cannot read ../demo-api (git exit 128); left"
                f" untouched Fix: {STATUS_FIX.format(dir='demo-api')}"
            )
        else:
            first = (
                "missing repo demo-api: ../demo-api exists but is not a git repository; left"
                f" untouched Fix: {MOVE_AWAY_FIX.format(dir='demo-api')}"
            )
        assert _repo_lines(result.stdout) == [first, "ok      repo demo-web: present, fetched"]
        # Only the empty ``.git`` folder is asked for a commit; nothing is ever fetched there.
        assert [call.args for call in env_traced_git.calls() if "demo-api" in call.args] == checks
        totals = "setup: 1 missing, 9 ok"
        if checks:
            assert demo_workspace.git(guarded, "for-each-ref") == refs
            # Doctor, read-only, reports the same folder: git puts it in the enclosing repo's tree.
            assert "error brain.leak ../demo-api: " in _doctor_lines(result.stdout)[1]
            totals = "setup: 2 missing, 8 ok"
        assert result.stdout.splitlines()[-1] == totals
        assert result.exit_code == 1

    def test_continues_after_failed_clone_when_origin_gone(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        demo_workspace.rewrite_github()
        _remove_repo(demo_workspace, "demo-web")
        shutil.rmtree(demo_workspace.origin("demo-web"))

        result = run_setup(demo_workspace.hub, "--yes")

        assert _repo_lines(result.stdout) == [
            "ok      repo demo-api: present, fetched",
            f"missing repo demo-web: clone failed (git exit 128) Fix: {_clone_fix('demo-web')}",
        ]
        assert not (Path(demo_workspace.ws) / "demo-web").exists()
        # Git's stderr names the origin's path: none of it is shown.
        for stream in (result.stdout_bytes, result.stderr_bytes):
            assert b"fatal" not in stream
            assert str(demo_workspace.origins).encode() not in stream
        assert result.stdout.splitlines()[-1] == "setup: 1 missing, 9 ok"
        assert result.exit_code == 1

    def test_continues_after_failed_fetch_when_origin_gone(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        shutil.rmtree(demo_workspace.origin("demo-api"))

        result = run_setup(demo_workspace.hub, "--yes")

        assert _repo_lines(result.stdout) == [
            "missing repo demo-api: fetch failed (git exit 128)"
            f" Fix: {FETCH_FIX.format(dir='demo-api')}",
            "ok      repo demo-web: present, fetched",
        ]
        for stream in (result.stdout_bytes, result.stderr_bytes):
            assert b"fatal" not in stream
            assert str(demo_workspace.origins).encode() not in stream
        assert result.stdout.splitlines()[-1] == "setup: 1 missing, 9 ok"
        assert result.exit_code == 1

    def test_reports_timeout_as_failed_when_clone_hangs(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        demo_workspace.rewrite_github()
        _remove_repo(demo_workspace, "demo-web")
        env_traced_git.hang_path.touch()
        monkeypatch.setattr(setup_repos, "NETWORK_TIMEOUT_SECONDS", 1.0)

        result = run_setup(demo_workspace.hub, "--yes")

        # The hanging git is a ``sleep`` that exits 0 when not killed: the text tells the timeout.
        assert _repo_lines(result.stdout) == [
            "missing repo demo-api: fetch timed out after 1 s"
            f" Fix: {FETCH_FIX.format(dir='demo-api')}",
            f"missing repo demo-web: clone timed out after 1 s Fix: {_clone_fix('demo-web')}",
        ]
        hung = _network_calls(env_traced_git)
        assert len(hung) == 2
        for call in hung:
            with pytest.raises(ProcessLookupError):
                os.kill(call.pid, 0)
        assert result.stdout.splitlines()[-1] == "setup: 2 missing, 8 ok"
        assert result.exit_code == 1

    def test_reports_failed_repos_when_git_not_found(
        self,
        demo_workspace: Workspace,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _remove_repo(demo_workspace, "demo-web")
        # The fake probe answers for the tools; git is on no PATH folder.
        no_git = tmp_path / "no-git-bin"
        no_git.mkdir()
        monkeypatch.setenv("PATH", str(no_git))

        result = run_setup(demo_workspace.hub, "--yes")

        assert _repo_lines(result.stdout) == [
            f"missing repo {repo}: git not found Fix: {GIT_FIX}"
            for repo in ("demo-api", "demo-web")
        ]
        assert not (Path(demo_workspace.ws) / "demo-web").exists()
        # Doctor cannot list the files without git either: an error of its own.
        assert _doctor_lines(result.stdout)[1].endswith(NO_GIT_FINDING_END)
        assert result.stdout.splitlines()[-1] == "setup: 3 missing, 7 ok"
        assert result.exit_code == 1

    def test_reports_failed_repos_when_git_cannot_run(
        self,
        demo_workspace: Workspace,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _remove_repo(demo_workspace, "demo-web")
        # On PATH and executable, but its interpreter does not exist: the exec fails.
        broken = tmp_path / "broken-git-bin"
        broken.mkdir()
        git = broken / "git"
        git.write_text(f"#!{tmp_path / 'no-such-interpreter'}\n", encoding="utf-8")
        git.chmod(0o755)
        monkeypatch.setenv("PATH", str(broken))

        result = run_setup(demo_workspace.hub, "--yes")

        assert _repo_lines(result.stdout) == [
            f"missing repo {repo}: git could not run Fix: {GIT_FIX}"
            for repo in ("demo-api", "demo-web")
        ]
        assert not (Path(demo_workspace.ws) / "demo-web").exists()
        # The checklist goes on: doctor's line and the totals still print.
        assert _doctor_lines(result.stdout)
        assert result.stdout.splitlines()[-1].startswith("setup: ")
        assert result.exit_code == 1

    def test_reports_unborn_repo_when_clone_was_interrupted(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        tree_digest: TreeDigest,
    ) -> None:
        ws = Path(demo_workspace.ws)
        path = ws / "demo-api"
        shutil.rmtree(path)
        # What a clone killed before its first checkout leaves: a repo with an origin, no commit.
        demo_workspace.git(ws, "init", "-q", "demo-api")
        demo_workspace.git(path, "remote", "add", "origin", str(demo_workspace.origin("demo-api")))
        before = (tree_digest(path), _mtimes(path))

        result = run_setup(demo_workspace.hub, "--yes")

        assert _repo_lines(result.stdout) == [
            "missing repo demo-api: ../demo-api has no commit (an interrupted clone?)"
            f" Fix: {MOVE_AWAY_FIX.format(dir='demo-api')}",
            "ok      repo demo-web: present, fetched",
        ]
        assert (tree_digest(path), _mtimes(path)) == before
        assert [call.args for call in _network_calls(env_traced_git)] == [
            f"-C {_ws(demo_workspace)}/demo-web fetch --quiet origin"
        ]
        assert result.stdout.splitlines()[-1] == "setup: 1 missing, 9 ok"
        assert result.exit_code == 1

    def test_reports_check_timeout_when_head_read_hangs(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        pid_log = _hang_head_read(env_traced_git, tmp_path, monkeypatch)
        monkeypatch.setattr(setup_repos, "CHECK_TIMEOUT_SECONDS", 0.5)

        result = run_setup(demo_workspace.hub, "--yes")

        # The check is named, not the fetch: no fetch ran in ../demo-api (E29).
        assert _repo_lines(result.stdout) == [
            "missing repo demo-api: checking ../demo-api timed out after 0.5 s"
            f" Fix: {STATUS_FIX.format(dir='demo-api')}",
            "ok      repo demo-web: present, fetched",
        ]
        assert [call.args for call in _network_calls(env_traced_git)] == [
            f"-C {_ws(demo_workspace)}/demo-web fetch --quiet origin"
        ]
        pids = [int(line) for line in pid_log.read_text(encoding="utf-8").split()]
        assert len(pids) == 1
        with pytest.raises(ProcessLookupError):
            os.kill(pids[0], 0)
        assert result.stdout.splitlines()[-1] == "setup: 1 missing, 9 ok"
        assert result.exit_code == 1

    def test_fetches_linked_repo_when_dir_is_symlink(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        ws = Path(demo_workspace.ws)
        real = Path(demo_workspace.base) / "elsewhere" / "demo-api"
        real.parent.mkdir()
        (ws / "demo-api").rename(real)
        (ws / "demo-api").symlink_to(real)

        result = run_setup(demo_workspace.hub, "--yes")

        assert _repo_lines(result.stdout) == [
            "ok      repo demo-api: present, fetched",
            "ok      repo demo-web: present, fetched",
        ]
        assert f"-C {_ws(demo_workspace)}/demo-api fetch --quiet origin" in [
            call.args for call in _network_calls(env_traced_git)
        ]
        # The fetch reached the linked clone: its origin branch is the origin's head.
        assert demo_workspace.git(real, "rev-parse", "origin/trunk") == (
            demo_workspace.origin_head("demo-api")
        )
        assert (ws / "demo-api").is_symlink()
        assert result.exit_code == 0, result.output


# Top level, so ``-k "scheme or url"`` selects it.
@pytest.mark.usefixtures("tools_ok")
class TestScheme:
    @pytest.mark.parametrize(
        "origin",
        ["git@github.com:acme/demo-hub.git", "ssh://git@github.com/acme/demo-hub.git"],
        ids=["scp", "ssh-url"],
    )
    def test_clones_ssh_url_when_hub_origin_is_ssh(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        origin: str,
    ) -> None:
        demo_workspace.rewrite_github()
        demo_workspace.init_hub_repo(origin)
        _remove_repo(demo_workspace, "demo-web")

        result = run_setup(demo_workspace.hub, "--yes")

        assert [
            call.args for call in _network_calls(env_traced_git) if call.args.startswith("clone ")
        ] == [f"clone --quiet git@github.com:acme/demo-web.git {_ws(demo_workspace)}/demo-web"]
        assert _repo_lines(result.stdout)[1] == _cloned_line("demo-web", "ssh")
        assert result.exit_code == 0, result.output

    @pytest.mark.parametrize(
        "origin",
        [
            f"https://x-access-token:{SYNTHETIC_TOKEN}@github.com/acme/demo-hub.git",
            "https://git.acme.test/acme/demo-hub.git",
        ],
        ids=["token-https", "other-host"],
    )
    def test_clones_https_url_when_hub_origin_not_github_ssh(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        origin: str,
    ) -> None:
        demo_workspace.rewrite_github()
        demo_workspace.init_hub_repo(origin)
        _remove_repo(demo_workspace, "demo-web")

        result = run_setup(demo_workspace.hub, "--yes")

        assert [
            call.args for call in _network_calls(env_traced_git) if call.args.startswith("clone ")
        ] == [f"clone --quiet https://github.com/acme/demo-web.git {_ws(demo_workspace)}/demo-web"]
        assert _repo_lines(result.stdout)[1] == _cloned_line("demo-web", "https")
        assert result.exit_code == 0, result.output

    def test_shows_no_remote_text_when_origin_holds_credential(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        demo_workspace.rewrite_github()
        demo_workspace.init_hub_repo(
            f"https://x-access-token:{SYNTHETIC_TOKEN}@github.com/acme/demo-hub.git"
        )
        _remove_repo(demo_workspace, "demo-web")

        result = run_setup(demo_workspace.hub, "--yes")

        for stream in (result.stdout_bytes, result.stderr_bytes):
            assert SYNTHETIC_TOKEN.encode() not in stream
            assert b"x-access-token" not in stream
            assert b"demo-hub" not in stream
            assert b"://" not in stream
        assert result.exit_code == 0, result.output


GOLDEN = Path(__file__).parent / "golden" / "setup"
GOLDEN_HINT = (
    "Update: GOLDEN_UPDATE=1 uv run --locked --all-packages pytest -m integration "
    "packages/cli/tests/integration/test_setup_command.py -q -k golden, "
    "then review and commit the golden diff"
)
_DOCTOR_LINE = re.compile(r"^(ok|missing) +hub doctor: ")
_READ_ONLY_GIT = ("config --get ", "rev-parse ", "ls-files ")
# A call's leading ``-c <name>=<value>`` options (doctor's git sets some): no subcommand.
_GIT_OPTIONS = re.compile(r"^(-c [^ ]+ )+")
# Setup's check that a present repo has a commit (``-C <repo>``, then a read): no write.
_COMMIT_CHECK = re.compile(r"^-C [^ ]+ rev-parse --verify -q HEAD$")
NO_GIT_FINDING_END = (
    "could not list the files: git not found Fix: fix the cause above so every file can be"
    " listed and read, then run hub doctor again"
)


def _doctor_lines(stdout: str) -> list[str]:
    """The ``hub doctor`` line and its sub-lines, up to the totals line."""
    lines = stdout.splitlines()
    start = next(index for index, line in enumerate(lines) if _DOCTOR_LINE.match(line))
    end = next(index for index, line in enumerate(lines) if _SUMMARY_LINE.match(line))
    return lines[start:end]


def _plant_check_override(hub: Path) -> int:
    """Give ``Makefile.project`` a rule for ``check``, a target the managed ``Makefile``
    defines; the line it is on."""
    project = hub / "Makefile.project"
    before = project.read_bytes()
    project.write_bytes(before + b"check:\n\t@echo ours\n")
    return len(before.splitlines()) + 1


def _override_line(line: int) -> str:
    return (
        f"{_SUB_LINE}warning makefile.override Makefile.project:{line}: redefines target 'check'"
        " Fix: rename the project target"
    )


def _give_repos_agents(workspace: Workspace) -> None:
    """Commit an empty ``AGENTS.md`` to each repo's origin and bring it into each clone there,
    so doctor's ``repos.agents`` finds nothing to say."""
    for repo in ("demo-api", "demo-web"):
        workspace.advance(repo, {"AGENTS.md": (b"", 0o644)})
        clone = Path(workspace.ws) / repo
        if clone.exists():
            workspace.git(clone, "pull", "-q", "--ff-only", "origin", "trunk")


def _work_tree(digest: Mapping[str, Any]) -> dict[str, Any]:
    """A digest or mtimes of a checkout without its ``.git`` folder, which a fetch updates."""
    return {
        path: entry
        for path, entry in digest.items()
        if path != ".git" and not path.startswith(".git/")
    }


@pytest.mark.usefixtures("tools_ok")
class TestDoctor:
    def test_runs_doctor_on_hub_root_when_cwd_elsewhere(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        hub = Path(demo_workspace.hub)
        _give_repos_agents(demo_workspace)
        line = _plant_check_override(hub)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setenv("AGENT_HUB_ROOT", str(hub))

        result = run_setup(elsewhere)

        assert _doctor_lines(result.stdout) == [
            "ok      hub doctor: 0 errors, 1 warning, 0 infos",
            _override_line(line),
        ]
        assert result.stdout.splitlines()[-1] == "setup: 10 ok"
        assert result.exit_code == 0, result.output

    def test_reports_missing_doctor_when_lock_drifts(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        hub = Path(demo_workspace.hub)
        _give_repos_agents(demo_workspace)
        (hub / "AGENTS.md").write_bytes(b"# edited\n")

        result = run_setup(hub)

        lines = _doctor_lines(result.stdout)
        assert lines[0] == f"missing hub doctor: 1 error, 0 warnings, 0 infos Fix: {DOCTOR_FIX}"
        assert len(lines) == 2
        assert lines[1].startswith(f"{_SUB_LINE}error lock.drift AGENTS.md")
        assert result.stdout.splitlines()[-1] == "setup: 1 missing, 9 ok"
        assert result.exit_code == 1

    @pytest.mark.parametrize("broken", ["non-utf8", "folder"])
    def test_reports_missing_doctor_when_lock_unreadable(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        broken: str,
    ) -> None:
        hub = Path(demo_workspace.hub)
        _give_repos_agents(demo_workspace)
        lock = hub / "hub.lock"
        lock.unlink()
        if broken == "folder":
            lock.mkdir()
        else:
            lock.write_bytes(b"\xff\xfe not utf-8\n")

        result = run_setup(hub)

        lines = _doctor_lines(result.stdout)
        assert lines[0] == f"missing hub doctor: 1 error, 0 warnings, 0 infos Fix: {DOCTOR_FIX}"
        assert len(lines) == 2
        assert lines[1].startswith(f"{_SUB_LINE}error lock.drift hub.lock")
        assert result.stdout.splitlines()[-1] == "setup: 1 missing, 9 ok"
        assert result.exit_code == 1
        assert "Traceback" not in result.stderr


@pytest.mark.usefixtures("tools_ok")
class TestIdempotent:
    def test_changes_nothing_when_idempotent_run_repeats(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        tree_digest: TreeDigest,
    ) -> None:
        hub = _team_hub(demo_workspace)
        demo_workspace.init_hub_repo(None)
        repos = [Path(demo_workspace.ws) / repo for repo in ("demo-api", "demo-web")]
        first = run_setup(hub, "--yes")
        assert first.exit_code == 0, first.output
        logged = len(env_traced_git.calls())
        local = _snapshot(hub / LOCAL_FILE)
        hub_before = (tree_digest(hub), _mtimes(hub))
        repos_before = [(_work_tree(tree_digest(r)), _work_tree(_mtimes(r))) for r in repos]

        second = run_setup(hub)

        calls = [call.args for call in env_traced_git.calls()[logged:]]
        assert not [args for args in calls if args.startswith("clone ")]
        assert [args for args in calls if " fetch " in f" {args} "] == [
            f"-C {_ws(demo_workspace)}/{repo} fetch --quiet origin"
            for repo in ("demo-api", "demo-web")
        ]
        # Every other call only reads: the fetches above, then config reads and the
        # check-ignore probe, none of which writes a working tree or a config.
        others = [args for args in calls if " fetch " not in f" {args} "]
        assert others
        for args in others:
            command = _GIT_OPTIONS.sub("", args)
            assert (
                command.startswith(_READ_ONLY_GIT)
                or " check-ignore -q " in command
                or _COMMIT_CHECK.match(command)
            ), args
        assert _snapshot(hub / LOCAL_FILE) == local
        assert (tree_digest(hub), _mtimes(hub)) == hub_before
        assert [(_work_tree(tree_digest(r)), _work_tree(_mtimes(r))) for r in repos] == repos_before
        assert second.stderr == ""
        assert second.exit_code == 0, second.output


class TestGolden:
    def test_matches_golden_when_mixed_case_runs(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        install_probe: ProbeInstaller,
        compare_text_golden: Callable[[bytes, Path, str], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # § Output's sample: a team hub with an SSH origin, demo-web missing, gh not logged
        # in, no LINEAR_API_KEY, doctor reporting one warning, run with --yes.
        demo_workspace.rewrite_github()
        hub = _team_hub(demo_workspace)
        demo_workspace.init_hub_repo("git@github.com:acme/demo-hub.git")
        _give_repos_agents(demo_workspace)
        _remove_repo(demo_workspace, "demo-web")
        _plant_check_override(hub)
        monkeypatch.delenv(KEY_VARIABLE, raising=False)
        install_probe(results={"gh": ProbeResult(1, b"", is_timed_out=False)})

        result = run_setup(hub, "--yes")

        compare_text_golden(result.stdout_bytes, GOLDEN / "mixed.golden", GOLDEN_HINT)
        assert result.exit_code == 1
