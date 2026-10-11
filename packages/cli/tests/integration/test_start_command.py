"""``hub start ISSUE``: from a tracker issue to its worktrees, its started state and a session.

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``: team ``DEM``,
repos ``demo-api`` and ``demo-web``, default branch ``trunk``, branch prefix ``jdoe/``), with
``traced_git`` logging each git call. The tracker is a ``RecordingTracker`` over
``tracker_backend_for_start()`` (plan E2), injected in place of
``start_command.resolve_tracker_client``. ``os.execvp`` is replaced by a recorder that keeps the
argv, the environment and the cwd, then raises, so nothing is exec'd (plan E3); ``claude`` on
``PATH`` is an empty executable put first, so git stays reachable.
"""

import os
import shutil
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import start_command
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.tracker.tracker_client import TrackerClient

pytestmark = pytest.mark.disable_socket

# The conftest's fixtures and objects (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any
type Tracker = Any
type Traced = Any

REPOS = ("demo-api", "demo-web")
ISSUE = "DEM-7"
NAME = "dem-7-add-the-collector"
BRANCH = "jdoe/dem-7-add-the-collector"
KEY_VARIABLE = "LINEAR_API_KEY"
VARIABLE = "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD"
SETUP = "scripts/worktree-setup.sh"
EXECUTABLE = 0o755
# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"
CLAUDE_MISSING = (
    "hub start: Claude Code (claude) is not on PATH;"
    " install it: https://docs.claude.com/en/docs/claude-code/setup"
)
MISSING_KEY = (
    'hub start: LINEAR_API_KEY is not set; export it, or set tracker.transport: "mcp"'
    " in hub.json to reach Linear through its MCP server with claude -p"
)


class Exec(NamedTuple):
    file: str
    argv: list[str]
    environ: dict[str, str]
    cwd: str


class Execed(Exception):  # noqa: N818 - the recorder's stop signal, not an error
    """Raised by the recorder in place of the exec."""


@pytest.fixture
def execs(monkeypatch: pytest.MonkeyPatch) -> list[Exec]:
    """Every ``os.execvp`` call, with the environment and cwd at that moment; the call raises."""
    calls: list[Exec] = []

    def record(file: str, argv: list[str]) -> None:
        calls.append(Exec(file, list(argv), dict(os.environ), os.getcwd()))
        raise Execed

    monkeypatch.setattr(os, "execvp", record)
    return calls


@pytest.fixture
def claude_first_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A folder holding an executable ``claude``, first on ``PATH``; ``os.environ`` restored."""
    folder = tmp_path / "claude-bin"
    folder.mkdir()
    claude = folder / "claude"
    claude.write_text("#!/bin/sh\nexit 0\n")
    claude.chmod(EXECUTABLE)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv(VARIABLE, raising=False)
    saved = dict(os.environ)
    yield folder
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VARIABLE, "lin" + "_api_" + "x" * 40)


class Resolve:
    """Replaces ``start_command.resolve_tracker_client``: records the hub root, returns
    ``client``."""

    def __init__(self, client: object) -> None:
        self.client = client
        self.roots: list[object] = []

    def __call__(self, config: HubConfig, environ: object, *, hub_root: object) -> TrackerClient:
        self.roots.append(hub_root)
        return self.client  # type: ignore[return-value]


def inject(monkeypatch: pytest.MonkeyPatch, client: object) -> Resolve:
    resolve = Resolve(client)
    monkeypatch.setattr(start_command, "resolve_tracker_client", resolve)
    return resolve


def git_lines(traced: Traced) -> list[tuple[str, str]]:
    """Each logged git call as ``(cwd, arguments)``."""
    if not traced.log_path.exists():
        return []
    lines = traced.log_path.read_text().splitlines()
    return [(cwd, arguments) for cwd, _, arguments in (line.partition("\t") for line in lines)]


def repo_git_calls(traced: Traced, workspace: Workspace) -> list[tuple[str, str]]:
    """The logged git calls whose cwd is in a repo of the workspace."""
    repos = [os.path.realpath(workspace.ws / repo) for repo in REPOS]
    return [
        (cwd, arguments)
        for cwd, arguments in git_lines(traced)
        if any(cwd == repo or cwd.startswith(repo + os.sep) for repo in repos)
    ]


def state_of(tracker: Tracker, issue_id: str = ISSUE) -> str:
    return str(tracker.backend.issues[issue_id].state)


def assert_usage(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout."""
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "Usage: hub start" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if message in text] == [message], shown


def assert_no_worktree(workspace: Workspace) -> None:
    for repo in REPOS:
        assert not (workspace.ws / repo / ".claude" / "worktrees").exists()


class StartRun:
    """A ``hub start`` run in the workspace: its git log, tracker, exec recorder and resolver."""

    def __init__(
        self,
        *,
        workspace: Workspace,
        traced: Traced,
        tracker: Tracker,
        execs: list[Exec],
        resolve: Resolve,
        runner: CommandRunner,
    ) -> None:
        self.workspace = workspace
        self.traced = traced
        self.tracker = tracker
        self.execs = execs
        self.resolve = resolve
        self._runner = runner

    def __call__(self, *arguments: str, env: Mapping[str, str | None] | None = None) -> Result:
        """``hub start <arguments>`` from the hub folder."""
        return self._runner(self.workspace.hub, "start", *arguments, env=env)

    def repo_git_calls(self) -> list[tuple[str, str]]:
        return repo_git_calls(self.traced, self.workspace)

    def worktree(self, repo: str, name: str = NAME) -> Path:
        return Path(self.workspace.worktree(repo, name))

    def state(self, issue_id: str = ISSUE) -> str:
        return state_of(self.tracker, issue_id)


@pytest.fixture
def hub_start(
    traced_git: Traced,
    demo_workspace: Workspace,
    run_command: CommandRunner,
    *,
    start_tracker: Tracker,
    execs: list[Exec],
    monkeypatch: pytest.MonkeyPatch,
) -> StartRun:
    """A run in the traced ``DEMO`` workspace with ``start_tracker`` injected."""
    return StartRun(
        workspace=demo_workspace,
        traced=traced_git,
        tracker=start_tracker,
        execs=execs,
        resolve=inject(monkeypatch, start_tracker),
        runner=run_command,
    )


def only_git_on_path(start: StartRun, folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``PATH`` = ``folder``, holding only the traced ``git``: no ``claude``."""
    folder.mkdir()
    (folder / "git").symlink_to(start.traced.bin_dir / "git")
    monkeypatch.setenv("PATH", str(folder))
    assert shutil.which("claude") is None


def logging_setup(log: Path) -> bytes:
    """A setup script that appends ``HUB_WORKTREE_NAME`` and its argument to ``log``."""
    return (
        f'#!/bin/sh\nprintf \'%s %s\\n\' "$HUB_WORKTREE_NAME" "$1" >> "{log}"\nexit 0\n'
    ).encode()


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestUsage:
    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            (["dem-7"], "issue must look like DEM-<n> (e.g. DEM-1)"),
            (["XYZ-1"], "issue must look like DEM-<n> (e.g. DEM-1)"),
            (
                ["DEM-7", "--repo", "nope"],
                "unknown repo in --repo: nope; use one of: demo-api demo-web",
            ),
        ],
        ids=["issue_lowercase", "team_unknown", "repo_unknown"],
    )
    def test_exits_two_before_tracker_and_git_when_usage_wrong(
        self, hub_start: StartRun, arguments: list[str], message: str
    ) -> None:
        result = hub_start(*arguments)

        assert_usage(result, message)
        assert hub_start.tracker.calls == []
        assert hub_start.repo_git_calls() == []
        assert_no_worktree(hub_start.workspace)
        assert hub_start.execs == []


@pytest.mark.usefixtures("with_key")
class TestMissing:
    def test_exits_one_before_tracker_when_claude_missing(
        self, hub_start: StartRun, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        only_git_on_path(hub_start, tmp_path / "only-git", monkeypatch)

        result = hub_start(ISSUE)

        assert result.exit_code == 1, result.output
        assert result.stderr == CLAUDE_MISSING + "\n"
        assert result.stdout == ""
        assert hub_start.tracker.calls == []
        assert hub_start.repo_git_calls() == []
        assert_no_worktree(hub_start.workspace)
        assert hub_start.execs == []

    def test_runs_without_claude_when_no_agent_given(
        self, hub_start: StartRun, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        only_git_on_path(hub_start, tmp_path / "only-git", monkeypatch)

        result = hub_start(ISSUE, "--no-agent")

        assert result.exit_code == 0, result.output
        assert hub_start.state() == "In Progress"
        for repo in REPOS:
            assert hub_start.worktree(repo).is_dir()
        assert hub_start.execs == []

    @pytest.mark.usefixtures("claude_first_on_path")
    def test_exits_one_without_request_when_key_missing(
        self, hub_start: StartRun, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KEY_VARIABLE, raising=False)

        result = hub_start(ISSUE)

        assert result.exit_code == 1, result.output
        assert result.stderr == MISSING_KEY + "\n"
        assert hub_start.tracker.calls == []
        assert hub_start.repo_git_calls() == []
        assert_no_worktree(hub_start.workspace)
        assert hub_start.execs == []


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestFresh:
    def test_creates_one_worktree_and_moves_issue_when_repo_given(
        self, hub_start: StartRun, tmp_path: Path
    ) -> None:
        log = tmp_path / "setup.log"
        head = hub_start.workspace.advance("demo-api", {SETUP: (logging_setup(log), EXECUTABLE)})

        result = hub_start(ISSUE, "--repo", "demo-api")

        assert isinstance(result.exception, Execed), result.output
        worktree = hub_start.worktree("demo-api")
        assert hub_start.workspace.git(worktree, "branch", "--show-current") == BRANCH
        # From a fresh fetch of origin/trunk (plan E4): the commit pushed after the clone.
        assert hub_start.workspace.git(worktree, "rev-parse", "HEAD") == head
        assert log.read_text() == f"{NAME} {worktree}\n"
        assert not (hub_start.workspace.ws / "demo-web" / ".claude").exists()
        assert hub_start.state() == "In Progress"
        assert hub_start.tracker.calls == [
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "In Progress"),
        ]
        assert hub_start.resolve.roots == [hub_start.workspace.hub]
        assert len(hub_start.execs) == 1
        assert f"created  {worktree} ({BRANCH} from origin/trunk)" in result.stdout.splitlines()
