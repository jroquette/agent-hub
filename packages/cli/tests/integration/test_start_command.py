"""``hub start ISSUE``: from a tracker issue to its worktrees, its started state and a session.

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``: team ``DEM``,
repos ``demo-api`` and ``demo-web``, default branch ``trunk``, branch prefix ``jdoe/``), with
``traced_git`` logging each git call. The tracker is a ``RecordingTracker`` over
``tracker_backend_for_start()`` (plan E2), injected in place of
``start_command.resolve_tracker_client``. ``os.execvp`` is replaced by a recorder that keeps the
argv, the environment and the cwd, then raises, so nothing is exec'd (plan E3); ``claude`` on
``PATH`` is an empty executable put first, so git stays reachable.
"""

import json
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
from agent_hub.core.workspace.agent_launch import settings_json
from agent_hub.core.workspace.start_prompt import start_prompt

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

    def __call__(self, *arguments: str) -> Result:
        """``hub start <arguments>`` from the hub folder."""
        return self.run_in(self.workspace.hub, *arguments)

    def run_in(
        self, folder: Path, *arguments: str, env: Mapping[str, str | None] | None = None
    ) -> Result:
        """``hub start <arguments>`` from ``folder``, with ``env`` as ``CliRunner``'s."""
        return self._runner(folder, "start", *arguments, env=env)

    def repo_git_calls(self) -> list[tuple[str, str]]:
        return repo_git_calls(self.traced, self.workspace)

    def hub_worktree(self, name: str, *arguments: str) -> None:
        """``hub worktree <name> <arguments>``, as a developer makes a task's worktrees; the git
        log is cleared afterwards, so it holds only what ``hub start`` runs."""
        made = self._runner(self.workspace.hub, "worktree", name, *arguments)
        assert made.exit_code == 0, made.output
        self.traced.log_path.unlink(missing_ok=True)

    def retitle(self, title: str, state: str) -> None:
        """Give DEM-7 another title and state in the tracker."""
        issues = self.tracker.backend.issues
        issues[ISSUE] = issues[ISSUE].model_copy(update={"title": title, "state": state})

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


def set_started_state(workspace: Workspace, state: str) -> None:
    """Set ``tracker.states.started`` in the hub's ``hub.json``."""
    path = workspace.hub / "hub.json"
    document = json.loads(path.read_text())
    document["tracker"]["states"] = {"started": state}
    path.write_text(json.dumps(document, indent=2) + "\n")


def stderr_lines(result: Result, prefix: str) -> list[str]:
    """The stderr lines that start with ``prefix``."""
    return [line for line in result.stderr.splitlines() if line.startswith(prefix)]


def stdout_starting(result: Result, prefix: str) -> list[str]:
    """The stdout lines that start with ``prefix``."""
    return [line for line in result.stdout.splitlines() if line.startswith(prefix)]


def logging_setup(log: Path) -> bytes:
    """A setup script that appends ``HUB_WORKTREE_NAME``, its argument and ``LINEAR_API_KEY``
    (``unset`` when unset) to ``log``."""
    return (
        "#!/bin/sh\n"
        f'printf \'%s %s %s\\n\' "$HUB_WORKTREE_NAME" "$1" "${{LINEAR_API_KEY-unset}}" >> "{log}"\n'
        "exit 0\n"
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
        # The key with_key sets reaches the tracker, never the repo's script.
        assert log.read_text() == f"{NAME} {worktree} unset\n"
        assert not (hub_start.workspace.ws / "demo-web" / ".claude").exists()
        assert hub_start.state() == "In Progress"
        assert hub_start.tracker.calls == [
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "In Progress"),
        ]
        assert hub_start.resolve.roots == [hub_start.workspace.hub]
        assert len(hub_start.execs) == 1
        assert f"created  {worktree} ({BRANCH} from origin/trunk)" in result.stdout.splitlines()


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestConventions:
    def test_creates_each_repo_on_its_branch_when_conventions_differ(
        self, hub_start: StartRun
    ) -> None:
        workspace = hub_start.workspace
        workspace.use_conventions(
            repos={"demo-web": {"branch": "{prefix}feature/{issue_lower}-{slug}"}}
        )
        workspace.use_repo_branch("demo-web", "develop")
        branches = {"demo-api": BRANCH, "demo-web": "jdoe/feature/dem-7-add-the-collector"}
        bases = {"demo-api": "trunk", "demo-web": "develop"}

        result = hub_start(ISSUE)

        assert isinstance(result.exception, Execed), result.output
        lines = result.stdout.splitlines()
        for repo in REPOS:
            worktree = hub_start.worktree(repo)
            assert f"created  {worktree} ({branches[repo]} from origin/{bases[repo]})" in lines
            assert workspace.git(worktree, "branch", "--show-current") == branches[repo]
            assert workspace.git(worktree, "rev-parse", "HEAD") == workspace.origin_head(
                repo, bases[repo]
            )
        assert f"task     : {NAME}" in lines
        assert [line for line in lines if line.startswith("branch   : ")] == [
            f"branch   : {repo} {branches[repo]}" for repo in REPOS
        ]


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestLaunch:
    def test_attaches_worktrees_from_main_checkout_when_launched(self, hub_start: StartRun) -> None:
        hub = hub_start.workspace.hub

        result = hub_start(ISSUE)

        assert isinstance(result.exception, Execed), result.output
        issue = hub_start.tracker.backend.issues[ISSUE]
        (launched,) = hub_start.execs
        assert launched.file == "claude"
        assert launched.cwd == os.path.realpath(hub)
        assert launched.argv == [
            "claude",
            "--add-dir",
            str(hub_start.worktree("demo-api")),
            "--add-dir",
            str(hub_start.worktree("demo-web")),
            "--append-system-prompt-file",
            str(hub / "brain" / "auto" / "agent-context-dem-7.md"),
            "--settings",
            settings_json(str(hub)),
            start_prompt(issue, task=NAME),
        ]
        for repo in REPOS:
            assert str(hub_start.workspace.ws / repo) not in launched.argv
        assert launched.environ[VARIABLE] == "1"

    def test_runs_from_main_checkout_when_started_from_hub_worktree(
        self, hub_start: StartRun
    ) -> None:
        workspace = hub_start.workspace
        hub = workspace.hub
        workspace.git(hub, "-c", "init.defaultBranch=main", "init", "-q")
        workspace.git(hub, "add", "-A")
        workspace.git(hub, "commit", "-q", "-m", "hub")
        hub_worktree = hub / ".claude" / "worktrees" / "x"
        workspace.git(hub, "worktree", "add", "-q", "-b", "x", str(hub_worktree))
        # Read from the worktree, this hub.json would exit 1: only the main checkout's is read.
        (hub_worktree / "hub.json").write_bytes(b"{}\n")

        result = hub_start.run_in(workspace.base, ISSUE, env={"AGENT_HUB_ROOT": str(hub_worktree)})

        assert isinstance(result.exception, Execed), result.output
        (launched,) = hub_start.execs
        assert launched.cwd == os.path.realpath(hub)
        context = hub / "brain" / "auto" / "agent-context-dem-7.md"
        assert launched.argv[5:9] == [
            "--append-system-prompt-file",
            str(context),
            "--settings",
            settings_json(str(hub)),
        ]
        assert context.is_file()
        assert hub_start.resolve.roots == [hub]

    def test_writes_task_context_file_when_launched(self, hub_start: StartRun) -> None:
        workspace = hub_start.workspace
        marker = b"# demo-api\nMARKER only on the task branch\n"
        workspace.advance("demo-api", {"AGENTS.md": (marker, 0o644)})
        assert not (workspace.ws / "demo-api" / "AGENTS.md").exists()

        result = hub_start(ISSUE)

        assert isinstance(result.exception, Execed), result.output
        auto = workspace.hub / "brain" / "auto"
        label = f"demo-api/.claude/worktrees/{NAME}"
        assert (auto / "agent-context-dem-7.md").read_bytes() == (
            f"\n# Instructions for ../{label} (from {label}/AGENTS.md)\n\n".encode() + marker
        )
        assert not (auto / "agent-context.md").exists()


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestRollback:
    def test_lists_both_and_drops_all_when_second_setup_fails(self, hub_start: StartRun) -> None:
        workspace = hub_start.workspace
        workspace.advance("demo-web", {SETUP: (b"#!/bin/sh\nexit 3\n", EXECUTABLE)})

        result = hub_start(ISSUE)

        assert result.exit_code == 1, result.output
        (line,) = stderr_lines(result, "hub start: ")
        assert line.startswith("hub start: demo-web: scripts/worktree-setup.sh exited 3;"), line
        assert stderr_lines(result, "created  : ") == [
            f"created  : {hub_start.worktree(repo)}" for repo in REPOS
        ]
        # Plan E10: the lines hub start prints after the error, not the script's own hint.
        assert stderr_lines(result, "remove   : ") == [f"remove   : ./hub worktree --remove {NAME}"]
        assert hub_start.state() == "Todo"
        assert [call for call in hub_start.tracker.calls if call[0] == "move_state"] == []
        assert hub_start.execs == []

    def test_prints_only_lines_when_some_repos_created(self, hub_start: StartRun) -> None:
        web = hub_start.workspace.ws / "demo-web"
        (web / ".git").rename(web / "git-away")

        result = hub_start(ISSUE)

        assert result.exit_code == 1, result.output
        assert stderr_lines(result, "hub start: ") == [
            f"hub start: {web} is not a git checkout; clone it next to the hub"
        ]
        assert stderr_lines(result, "created  : ") == [
            f"created  : {hub_start.worktree('demo-api')}"
        ]
        assert stderr_lines(result, "remove   : ") == [
            f"remove   : ./hub worktree --remove {NAME} --only demo-api"
        ]
        assert hub_start.state() == "Todo"
        assert hub_start.execs == []


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestTracker:
    def test_keeps_and_lists_worktrees_when_started_state_unknown(
        self, hub_start: StartRun
    ) -> None:
        set_started_state(hub_start.workspace, "Doing")

        result = hub_start(ISSUE)

        assert result.exit_code == 1, result.output
        assert stderr_lines(result, "hub start: ") == [
            "hub start: move_state DEM-7: state 'Doing' not found in team DEM;"
            " use one of: Todo, In Progress, In Review, Done"
        ]
        assert stderr_lines(result, "created  : ") == [
            f"created  : {hub_start.worktree(repo)}" for repo in REPOS
        ]
        assert stderr_lines(result, "remove   : ") == [f"remove   : ./hub worktree --remove {NAME}"]
        for repo in REPOS:
            assert hub_start.worktree(repo).is_dir()
        assert hub_start.state() == "Todo"
        assert hub_start.execs == []

    def test_creates_nothing_when_issue_unknown(self, hub_start: StartRun) -> None:
        result = hub_start("DEM-99")

        assert result.exit_code == 1, result.output
        (line,) = stderr_lines(result, "hub start: ")
        assert line.startswith("hub start: get_issue DEM-99: "), line
        assert stderr_lines(result, "created  : ") == []
        assert hub_start.tracker.calls == [("get_issue", "DEM-99")]
        assert [call for call in hub_start.repo_git_calls() if "fetch" in call[1]] == []
        assert_no_worktree(hub_start.workspace)
        assert hub_start.execs == []


OLD = "dem-7-old-title"
CONDITIONAL_MOVE = ("move_state", ISSUE, "In Progress", "only_if_unstarted")


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestResume:
    def test_reuses_worktrees_and_keeps_state_when_issue_in_review(
        self, hub_start: StartRun
    ) -> None:
        hub_start.hub_worktree(OLD)
        hub_start.hub_worktree("dem-70-x", "--only", "demo-api")
        hub_start.retitle("A retitled issue", "In Review")

        result = hub_start(ISSUE)

        assert isinstance(result.exception, Execed), result.output
        assert stdout_starting(result, "exists   ") == [
            f"exists   {hub_start.worktree(repo, OLD)}" for repo in REPOS
        ]
        assert stdout_starting(result, "created  ") == []
        assert "state    : In Review (already started, not moved)" in result.stdout.splitlines()
        # Plan E5: one conditional move, which leaves a started issue as it is.
        assert hub_start.tracker.calls == [("get_issue", ISSUE), CONDITIONAL_MOVE]
        assert hub_start.state() == "In Review"
        (launched,) = hub_start.execs
        assert launched.argv[1:5] == [
            "--add-dir",
            str(hub_start.worktree("demo-api", OLD)),
            "--add-dir",
            str(hub_start.worktree("demo-web", OLD)),
        ]
        assert not hub_start.worktree("demo-api").exists()

    def test_creates_missing_repo_under_existing_name_when_partial(
        self, hub_start: StartRun
    ) -> None:
        hub_start.hub_worktree(OLD, "--only", "demo-api")
        hub_start.retitle("A retitled issue", "In Progress")

        result = hub_start(ISSUE)

        assert isinstance(result.exception, Execed), result.output
        web = hub_start.worktree("demo-web", OLD)
        assert stdout_starting(result, "exists   ") == [
            f"exists   {hub_start.worktree('demo-api', OLD)}"
        ]
        assert stdout_starting(result, "created  ") == [
            f"created  {web} (jdoe/{OLD} from origin/trunk)"
        ]
        assert hub_start.workspace.git(web, "branch", "--show-current") == f"jdoe/{OLD}"
        assert hub_start.tracker.calls == [("get_issue", ISSUE), CONDITIONAL_MOVE]
        assert hub_start.state() == "In Progress"

    def test_resumes_name_found_in_untouched_repo_when_repo_given(
        self, hub_start: StartRun
    ) -> None:
        hub_start.hub_worktree(OLD, "--only", "demo-web")

        result = hub_start(ISSUE, "--repo", "demo-api")

        assert isinstance(result.exception, Execed), result.output
        assert hub_start.worktree("demo-api", OLD).is_dir()
        assert not hub_start.worktree("demo-api").exists()
        (launched,) = hub_start.execs
        assert launched.argv[1:3] == ["--add-dir", str(hub_start.worktree("demo-api", OLD))]
        assert hub_start.tracker.calls == [("get_issue", ISSUE), CONDITIONAL_MOVE]

    def test_moves_unstarted_issue_when_resumed(self, hub_start: StartRun) -> None:
        hub_start.hub_worktree(OLD)

        result = hub_start(ISSUE)

        assert isinstance(result.exception, Execed), result.output
        assert stdout_starting(result, "created  ") == []
        assert hub_start.tracker.calls == [("get_issue", ISSUE), CONDITIONAL_MOVE]
        assert hub_start.state() == "In Progress"
        assert "state    : In Progress" in result.stdout.splitlines()
        assert len(hub_start.execs) == 1


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestAmbiguous:
    @pytest.mark.parametrize(
        ("made", "listed"),
        [
            (
                [("dem-7-a", "demo-api"), ("dem-7-b", "demo-api")],
                "demo-api: dem-7-a, dem-7-b",
            ),
            (
                [("dem-7-a", "demo-api"), ("dem-7-b", "demo-web")],
                "demo-api: dem-7-a; demo-web: dem-7-b",
            ),
        ],
        ids=["repo_has_two_matches", "repos_disagree"],
    )
    def test_refuses_before_fetch_when_tasks_ambiguous(
        self, hub_start: StartRun, made: list[tuple[str, str]], listed: str
    ) -> None:
        for name, repo in made:
            hub_start.hub_worktree(name, "--only", repo)

        result = hub_start(ISSUE)

        assert result.exit_code == 1, result.output
        (line,) = stderr_lines(result, "hub start: ")
        assert line.startswith(
            f"hub start: worktrees of more than one task match the issue ({listed});"
        ), line
        assert [
            arguments
            for _, arguments in hub_start.repo_git_calls()
            if arguments.startswith(("fetch", "worktree add"))
        ] == []
        assert hub_start.tracker.calls == [("get_issue", ISSUE)]
        assert hub_start.state() == "Todo"
        assert hub_start.execs == []


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestNoAgent:
    def test_prints_summary_and_next_step_when_no_agent_given(self, hub_start: StartRun) -> None:
        result = hub_start(ISSUE, "--repo", "demo-api", "--no-agent")

        assert result.exit_code == 0, result.output
        assert hub_start.state() == "In Progress"
        assert hub_start.execs == []
        assert result.stdout.splitlines()[-7:] == [
            "",
            f"task     : {NAME} (branch {BRANCH})",
            "repos    : demo-api",
            f"worktree : {hub_start.worktree('demo-api')}",
            "state    : In Progress",
            f"remove   : ./hub worktree --remove {NAME} --only demo-api",
            "next     : ./hub start DEM-7 --repo demo-api",
        ]


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestLaunchFailure:
    def test_lists_moved_state_and_worktrees_when_exec_fails(
        self, hub_start: StartRun, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(_file: str, _argv: list[str]) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(os, "execvp", refuse)

        result = hub_start(ISSUE, "--repo", "demo-api")

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[1:] == [
            "hub start: cannot start claude: Permission denied",
            "state    : DEM-7 was moved to In Progress; ./hub start DEM-7 --repo demo-api"
            " resumes the task",
            f"created  : {hub_start.worktree('demo-api')}",
            f"remove   : ./hub worktree --remove {NAME} --only demo-api",
        ]
        assert hub_start.state() == "In Progress"


@pytest.mark.usefixtures("with_key", "claude_first_on_path")
class TestShownText:
    def test_escapes_state_when_tracker_state_holds_control_characters(
        self, hub_start: StartRun
    ) -> None:
        state = "In \x1b[31mReview\nforged : line"
        hub_start.hub_worktree(OLD)
        hub_start.retitle("A retitled issue", state)

        result = hub_start(ISSUE, "--no-agent")

        assert result.exit_code == 0, result.output
        assert stdout_starting(result, "state    : ") == [
            f"state    : {json.dumps(state)} (already started, not moved)"
        ]
        assert "\x1b" not in result.stdout
        assert "forged : line" not in result.stdout.splitlines()

    def test_names_issue_argument_when_tracker_answers_other_id(self, hub_start: StartRun) -> None:
        issues = hub_start.tracker.backend.issues
        issues[ISSUE] = issues[ISSUE].model_copy(update={"id": "DEM-77"})

        result = hub_start(ISSUE, "--repo", "demo-api", "--no-agent")

        assert result.exit_code == 0, result.output
        assert stdout_starting(result, "next     : ") == [
            "next     : ./hub start DEM-7 --repo demo-api"
        ]


@pytest.mark.usefixtures("with_key")
class TestHubCheckout:
    def test_exits_one_when_git_missing_and_root_is_hub_worktree(
        self, hub_start: StartRun, claude_first_on_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = hub_start.workspace
        hub = workspace.hub
        workspace.git(hub, "-c", "init.defaultBranch=main", "init", "-q")
        workspace.git(hub, "add", "-A")
        workspace.git(hub, "commit", "-q", "-m", "hub")
        hub_worktree = hub / ".claude" / "worktrees" / "x"
        workspace.git(hub, "worktree", "add", "-q", "-b", "x", str(hub_worktree))
        # Falling back to the worktree as the hub would read this hub.json and exit on it.
        (hub_worktree / "hub.json").write_bytes(b"{}\n")
        monkeypatch.setenv("PATH", str(claude_first_on_path))

        result = hub_start.run_in(workspace.base, ISSUE, env={"AGENT_HUB_ROOT": str(hub_worktree)})

        assert result.exit_code == 1, result.output
        assert result.stderr == "hub start: git is not on PATH; install git\n"
        assert hub_start.tracker.calls == []
        assert hub_start.execs == []
