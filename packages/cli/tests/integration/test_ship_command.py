"""``hub ship``: an issue's task worktrees checked, pushed, opened as PRs, linked (AC-63.3 on).

Every case runs in process, in a copy of the ``DEMO`` workspace (spec E2: team ``DEM``, repos
``demo-api`` and ``demo-web``, default branch ``trunk``, branch prefix ``jdoe/``), with
``PATH`` holding only the fakes, ``git``, ``bash`` and the interpreter (``ship_workspace``). Its
``gh`` is a scripted fake whose PRs live in a JSON state file; the tracker is a recording
in-memory one (``ship_tracker``).
"""

import json
import os
import time
from collections.abc import Callable
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import run_steps, ship_command, ship_set, ship_steps
from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.run_children import push_command, shown_command
from agent_hub.core.doctor.text_rules import ATTRIBUTIONS
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.runner.run_texts import ROBOT
from agent_hub.core.runner.ship_texts import RELATED_END, RELATED_START
from agent_hub.core.testing.builders import a_conventions_document
from agent_hub.core.tracker.tracker_client import TrackerClient

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

API_GITHUB = "acme/demo-api"
ISSUE = "DEM-7"
KEY_VARIABLE = "LINEAR_API_KEY"
# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"
SHAPE = "issue must look like DEM-<n> (e.g. DEM-1)"


def synthetic_key() -> str:
    return "lin" + "_api_" + "x" * 40


class Resolve:
    """Replaces ``ship_command.resolve_tracker_client``: records the hub root, returns
    ``client``."""

    def __init__(self, client: object) -> None:
        self.client = client
        self.roots: list[object] = []

    def __call__(self, config: HubConfig, environ: object, *, hub_root: object) -> TrackerClient:
        self.roots.append(hub_root)
        return self.client  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # A usage message stays on one line of Rich's box.
    monkeypatch.setenv("COLUMNS", "200")


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VARIABLE, synthetic_key())


@pytest.fixture
def tracker(ship_tracker: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """``ship_tracker``, the client every ``hub ship`` of the test resolves."""
    monkeypatch.setattr(ship_command, "resolve_tracker_client", Resolve(ship_tracker))
    return ship_tracker


def assert_refused(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout."""
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "Usage: hub ship" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if message in text] == [message], shown


def set_transport(hub: Any, transport: str) -> None:
    document = json.loads((hub / "hub.json").read_text())
    document["tracker"]["transport"] = transport
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")


def fake_gh(ship_workspace: Workspace, *arguments: str) -> ChildResult:
    """Run the fake ``gh`` with ``arguments`` in the hub, with the test's environment."""
    return run_child(
        [str(ship_workspace.bin / "gh"), *arguments],
        cwd=ship_workspace.workspace.hub,
        env=dict(os.environ),
        timeout=60,
    )


def create_argv(branch: str, *, body: str = "DEM-7") -> list[str]:
    return [
        *("pr", "create", "--repo", API_GITHUB, "--base", "trunk", "--head", branch),
        *("--title", "feat(api): x (DEM-7)", "--body", body),
    ]


class TestShipFakes:
    @pytest.mark.parametrize(
        "arguments",
        [
            ("pr", "merge", "https://github.com/acme/demo-api/pull/101"),
            ("pr", "view", "jdoe/dem-7", "--repo", API_GITHUB, "--json", "url,author"),
            ("pr", "view", "jdoe/dem-7", "--repo", API_GITHUB),
            ("pr", "create", "--repo", API_GITHUB, "--head", "jdoe/dem-7"),
            ("pr", "edit", "https://github.com/acme/demo-api/pull/101", "--title", "x"),
            ("api", "repos/acme/demo-api"),
            (),
        ],
        ids=["merge", "unknown-field", "no-json", "create-partial", "edit-title", "api", "none"],
    )
    def test_refuses_unknown_argv_when_fake_gh_called(
        self, ship_workspace: Workspace, *, arguments: tuple[str, ...]
    ) -> None:
        result = fake_gh(ship_workspace, *arguments)

        assert result.returncode == 2, result.stderr
        assert ship_workspace.prs() == []
        assert [call["argv"] for call in ship_workspace.calls("gh")] == [list(arguments)]

    def test_finds_pr_when_created_before(self, ship_workspace: Workspace) -> None:
        created = fake_gh(ship_workspace, *create_argv("jdoe/dem-7"))
        again = fake_gh(ship_workspace, *create_argv("jdoe/dem-7", body="other"))
        viewed = fake_gh(
            ship_workspace, "pr", "view", "jdoe/dem-7", "--repo", API_GITHUB, "--json", "url,state"
        )
        url = "https://github.com/acme/demo-api/pull/101"
        edited = fake_gh(ship_workspace, "pr", "edit", url, "--body", "DEM-7 linked")
        body = fake_gh(ship_workspace, "pr", "view", url, "--json", "body")

        assert (created.returncode, created.stdout.decode()) == (0, f"{url}\n")
        assert again.returncode == 1
        assert url in again.stderr.decode()
        assert viewed.returncode == 0
        assert json.loads(viewed.stdout) == {"url": url, "state": "OPEN"}
        assert edited.returncode == 0
        assert json.loads(body.stdout) == {"body": "DEM-7 linked"}
        assert ship_workspace.prs() == [
            {
                "repo": API_GITHUB,
                "head": "jdoe/dem-7",
                "base": "trunk",
                "title": "feat(api): x (DEM-7)",
                "url": url,
                "state": "OPEN",
                "body": "DEM-7 linked",
                "draft": False,
            }
        ]

    def test_fails_named_step_when_fake_gh_told_to(
        self, ship_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_GH_FAIL", "create:demo-web,view:demo-api")

        created = fake_gh(ship_workspace, *create_argv("jdoe/dem-7"))
        viewed = fake_gh(
            ship_workspace, "pr", "view", "jdoe/dem-7", "--repo", API_GITHUB, "--json", "url,state"
        )
        web = [
            *("pr", "create", "--repo", "acme/demo-web", "--base", "trunk"),
            *("--head", "jdoe/dem-7", "--title", "t", "--body", "b", "--draft"),
        ]
        refused = fake_gh(ship_workspace, *web)

        assert created.returncode == 0
        assert viewed.returncode == 1
        assert refused.returncode == 1
        assert [pr["repo"] for pr in ship_workspace.prs()] == [API_GITHUB]

    def test_records_issue_and_failed_label_when_ship_tracker_built(
        self, ship_tracker: Any, tracker_backend_for_ship: Callable[..., Any]
    ) -> None:
        issue = ship_tracker.backend.issues["DEM-7"]
        failed = tracker_backend_for_ship(failed=True, states=("Todo", "Code Review"))

        assert issue.url == "https://linear.app/demo/issue/DEM-7"
        assert "agent-failed" not in issue.labels
        assert "agent-failed" in failed.issues["DEM-7"].labels
        assert [state.name for state in failed.states["DEM"]] == ["Todo", "Code Review"]

    def test_commits_subjects_when_task_worktree_made(
        self,
        ship_workspace: Workspace,
        make_task_worktree: Callable[..., Any],
        *,
        child_calls: Any,
    ) -> None:
        worktree = make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)", "fix: b"])
        child_calls.clear()

        log = ship_workspace.workspace.git(worktree, "log", "--format=%s", "origin/trunk..HEAD")
        branch = ship_workspace.workspace.git(worktree, "branch", "--show-current")
        ship_set.run_child(["git", "--version"], cwd=worktree, env=dict(os.environ), timeout=60)

        assert log.splitlines() == ["fix: b", "feat(api): a (DEM-7)"]
        assert branch == "jdoe/dem-7-x"
        assert [(call.argv, call.cwd, call.timeout) for call in child_calls.calls] == [
            (["git", "--version"], worktree, 60)
        ]


@pytest.mark.usefixtures("with_key")
class TestShipUsage:
    def test_lists_options_when_help_requested(
        self, ship_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(ship_workspace.workspace.hub, "ship", "--help")

        assert result.exit_code == 0
        words = " ".join(unstyle(result.stdout).replace(BOX_CHARACTERS[0], " ").split())
        for text in ("[ISSUE]", "--draft", "--dry-run", "posts one more comment"):
            assert text in words, text
        assert "--skip-check" not in words

    @pytest.mark.parametrize("issue", ["dem-1", "OPS-1", "DEM-0", "DEM-1x"])
    def test_refuses_issue_when_malformed(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        tracker: Any,
        child_calls: Any,
        issue: str,
    ) -> None:
        result = run_command(ship_workspace.workspace.hub, "ship", issue)

        assert_refused(result, SHAPE)
        assert child_calls.calls == []
        assert tracker.calls == []

    def test_refuses_when_two_issues_given(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        result = run_command(ship_workspace.workspace.hub, "ship", "DEM-7", "DEM-8")

        assert_refused(result, "Got unexpected extra argument(s) (DEM-8)")
        assert child_calls.calls == []
        assert tracker.calls == []

    def test_refuses_when_folder_has_no_hub(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        ws = ship_workspace.workspace.ws

        result = run_command(ws, "ship", ISSUE)

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{ws}: not a hub: no hub.json in this folder"
            " (hub ship runs in the hub folder or through ./hub)\n"
        )
        assert child_calls.calls == []
        assert tracker.calls == []

    def test_names_key_when_api_key_missing(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        set_transport(ship_workspace.workspace.hub, "api")
        monkeypatch.delenv(KEY_VARIABLE)

        result = run_command(ship_workspace.workspace.hub, "ship", ISSUE)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == (
            'hub ship: LINEAR_API_KEY is not set; export it, or set tracker.transport: "mcp"'
            " in hub.json to reach Linear through its MCP server with claude -p\n"
        )
        assert child_calls.calls == []
        assert tracker.calls == []

    def test_stops_before_children_when_issue_read_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): x (DEM-7)"])
        child_calls.clear()
        tracker.fail_on.add("get_issue")

        result = run_command(ship_workspace.workspace.hub, "ship", ISSUE)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.splitlines()[-1] == "hub ship: get_issue DEM-7: synthetic outage"
        assert child_calls.calls == []
        assert tracker.calls == [("get_issue", ISSUE)]

    def test_exits_as_run_when_hub_json_invalid(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        hub = ship_workspace.workspace.hub
        (hub / "hub.json").write_text('{"schema_version": 1, "project": 3}\n')

        shipped = run_command(hub, "ship", ISSUE)
        ran = run_command(hub, "run", ISSUE, "--repo", "demo-api")

        assert shipped.exit_code == ran.exit_code == 1
        assert shipped.stdout == ""
        assert shipped.stderr == ran.stderr != ""
        assert child_calls.calls == []
        assert tracker.calls == []


def use_mixed_hub(ship_workspace: Workspace) -> None:
    """The mixed-conventions hub of AC 57.7 (``a_conventions_document``)."""
    mixed = a_conventions_document()
    api = next(repo["conventions"] for repo in mixed["repos"] if repo["dir"] == "demo-api")
    ship_workspace.workspace.use_conventions(
        project=mixed["project"]["conventions"], repos={"demo-api": api}
    )


def assert_nothing_shipped(ship_workspace: Workspace, child_calls: Any, tracker: Any) -> None:
    """Only git read: no check, push, ``gh`` or tracker write."""
    assert set(child_calls.programs()) <= {"git"}
    assert [call.argv for call in child_calls.calls if "push" in call.argv] == []
    for tool in ("gh", "make"):
        assert ship_workspace.calls(tool) == []
    assert tracker.calls == [("get_issue", ISSUE)]


@pytest.mark.usefixtures("with_key")
class TestShipSet:
    def test_names_skipped_repo_when_dry_run(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)", "fix(api): b (DEM-7)"])
        make_task_worktree("demo-web", "dem-7", [])

        result = run_command(ship_workspace.workspace.hub, "ship", ISSUE, "--dry-run")

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[:2] == [
            "ship: demo-api  jdoe/dem-7-x",
            "skipped: demo-web (no commits ahead of origin/trunk)",
        ]
        assert tracker.calls == [("get_issue", ISSUE)]

    def test_ignores_longer_issue_number_when_dry_run(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)"])
        make_task_worktree("demo-api", "dem-70", ["feat(api): c (DEM-70)"])
        make_task_worktree("demo-web", "dem-70", ["feat(web): c (DEM-70)"])

        result = run_command(ship_workspace.workspace.hub, "ship", ISSUE, "--dry-run")

        assert result.exit_code == 0, result.output
        lines = result.stdout.splitlines()
        assert lines[0] == "ship: demo-api  jdoe/dem-7-x"
        assert not [line for line in lines if "dem-70" in line or "demo-web" in line]

    def test_uses_repo_branch_convention_when_hub_mixed(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
    ) -> None:
        use_mixed_hub(ship_workspace)
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)"])
        make_task_worktree("demo-web", "dem-7-x", ["feat(web): a (DEM-7)"])

        result = run_command(ship_workspace.workspace.hub, "ship", ISSUE, "--dry-run")

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[:2] == [
            "ship: demo-api  feature/dem-7/x",
            "ship: demo-web  jdoe/DEM-7-x",
        ]


@pytest.mark.usefixtures("with_key")
class TestShipRefusals:
    def refused(
        self, ship_workspace: Workspace, run_command: CommandRunner, *, child_calls: Any
    ) -> Result:
        """``hub ship DEM-7`` after the test's setup: exit 1, one stderr line after the
        transport's, nothing on stdout."""
        child_calls.clear()
        result = run_command(ship_workspace.workspace.hub, "ship", ISSUE)
        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        assert len(result.stderr.splitlines()) == 2, result.stderr
        return result

    def test_names_both_paths_when_repo_has_two_task_worktrees(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        short = make_task_worktree("demo-api", "dem-7", ["feat(api): a (DEM-7)"])
        longer = make_task_worktree("demo-api", "dem-7-x", ["feat(api): b (DEM-7)"])

        result = self.refused(ship_workspace, run_command, child_calls=child_calls)

        assert result.stderr.splitlines()[-1] == (
            f"hub ship: demo-api: more than one task worktree for DEM-7: {short}, {longer};"
            " remove one (hub worktree --remove <name>)"
        )
        assert_nothing_shipped(ship_workspace, child_calls, tracker)

    def test_names_issue_and_repos_when_no_task_worktree(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-70", ["feat(api): a (DEM-70)"])

        result = self.refused(ship_workspace, run_command, child_calls=child_calls)

        assert result.stderr.splitlines()[-1] == (
            "hub ship: no task worktree for DEM-7 in demo-api, demo-web"
            " (looked for <repo>/.claude/worktrees/dem-7[-<desc>])"
        )
        assert_nothing_shipped(ship_workspace, child_calls, tracker)

    def test_refuses_when_no_repo_ahead(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", [])
        make_task_worktree("demo-web", "dem-7", [])

        result = self.refused(ship_workspace, run_command, child_calls=child_calls)

        assert result.stderr.splitlines()[-1] == (
            "hub ship: no repo has commits ahead of its base for DEM-7:"
            " demo-api (origin/trunk), demo-web (origin/trunk)"
        )
        assert_nothing_shipped(ship_workspace, child_calls, tracker)

    def test_names_branches_when_worktree_on_other_branch(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        worktree = make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)"])
        make_task_worktree("demo-web", "dem-7", ["feat(web): a (DEM-7)"])
        ship_workspace.workspace.git(worktree, "switch", "-q", "-c", "jdoe/other")

        result = self.refused(ship_workspace, run_command, child_calls=child_calls)

        assert result.stderr.splitlines()[-1] == (
            f"hub ship: demo-api: {worktree} is on jdoe/other, not jdoe/dem-7-x"
        )
        assert_nothing_shipped(ship_workspace, child_calls, tracker)

    def test_names_folder_when_worktree_has_no_git_entry(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)"])
        folder = ship_workspace.workspace.worktree("demo-web", "dem-7")
        folder.mkdir(parents=True)

        result = self.refused(ship_workspace, run_command, child_calls=child_calls)

        assert result.stderr.splitlines()[-1] == (
            f"hub ship: demo-web: {folder} is not a git worktree: it has no .git entry"
        )
        assert_nothing_shipped(ship_workspace, child_calls, tracker)

    def test_names_folder_when_worktrees_unlistable(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)"])
        folder = ship_workspace.workspace.ws / "demo-web" / ".claude" / "worktrees"
        folder.parent.mkdir(parents=True)
        folder.write_text("not a folder\n")

        result = self.refused(ship_workspace, run_command, child_calls=child_calls)

        assert result.stderr.splitlines()[-1] == (
            f"hub ship: demo-web: cannot list {folder}: Not a directory"
        )
        assert_nothing_shipped(ship_workspace, child_calls, tracker)

    def test_names_repo_when_base_ref_missing(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        worktree = make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)"])
        ship_workspace.workspace.git(
            ship_workspace.workspace.ws / "demo-api",
            "update-ref",
            "-d",
            "refs/remotes/origin/trunk",
        )

        result = self.refused(ship_workspace, run_command, child_calls=child_calls)

        line = result.stderr.splitlines()[-1]
        assert line.startswith(f"hub ship: demo-api: git rev-list failed in {worktree}: ")
        assert "origin/trunk" in line
        assert_nothing_shipped(ship_workspace, child_calls, tracker)


NOT_IN_TASK_WORKTREE = (
    "give ISSUE or run hub ship from a task worktree (<repo>/.claude/worktrees/<team>-<n>[-<desc>])"
)


def shipped_children(ship_workspace: Workspace, child_calls: Any) -> list[tuple[Any, ...]]:
    """What a ship ran: each child's argv and cwd, then each ``gh`` call's argv and cwd."""
    children = [(tuple(call.argv), call.cwd) for call in child_calls.calls]
    gh = [(tuple(call["argv"]), call["cwd"]) for call in ship_workspace.calls("gh")]
    return [*children, *gh]


def forget_ship(ship_workspace: Workspace, child_calls: Any, *, branch: str) -> None:
    """Undo what a ship left outside the worktree: the PRs, the pushed branch, the calls."""
    ship_workspace.state.unlink(missing_ok=True)
    origin = ship_workspace.workspace.origin("demo-api")
    ship_workspace.workspace.git(origin, "update-ref", "-d", f"refs/heads/{branch}")
    (ship_workspace.logs / "gh.jsonl").unlink(missing_ok=True)
    child_calls.clear()


@pytest.mark.usefixtures("with_key")
class TestShipNoArgument:
    @pytest.mark.parametrize("below", [False, True], ids=["root", "below"])
    def test_ships_worktree_issue_when_run_from_worktree(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
        below: bool,
    ) -> None:
        hub = ship_workspace.workspace.hub
        worktree = make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)"])
        cwd = worktree / "src" if below else worktree
        cwd.mkdir(exist_ok=True)
        monkeypatch.setenv("AGENT_HUB_ROOT", str(hub))
        child_calls.clear()

        from_cwd = run_command(cwd, "ship")
        derived = shipped_children(ship_workspace, child_calls)
        forget_ship(ship_workspace, child_calls, branch="jdoe/dem-7-x")
        explicit = run_command(hub, "ship", ISSUE)

        assert from_cwd.exit_code == explicit.exit_code == 0, from_cwd.output
        assert from_cwd.stdout == explicit.stdout
        assert derived == shipped_children(ship_workspace, child_calls)
        assert derived != []
        # Each run reads the issue, then makes the same writes.
        shipped = [
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "In Review"),
            ("comment", ISSUE, f"Pull requests:\n- {API_PR}"),
        ]
        assert tracker.calls == shipped * 2

    def test_maps_team_spelling_when_hub_has_two_teams(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ship_workspace.workspace.use_teams("APP", "OPS")
        issue = tracker.backend.issues[ISSUE]
        tracker.backend.issues["OPS-3"] = issue.model_copy(update={"id": "OPS-3"})
        worktree = make_task_worktree("demo-api", "ops-3", ["feat(api): a (OPS-3)"])
        monkeypatch.setenv("AGENT_HUB_ROOT", str(ship_workspace.workspace.hub))

        result = run_command(worktree, "ship", "--dry-run")

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[0] == "ship: demo-api  jdoe/ops-3"
        assert tracker.calls == [("get_issue", "OPS-3")]

    @pytest.mark.parametrize("folder", ["hub", "main-checkout"])
    def test_refuses_when_cwd_outside_task_worktree(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
        folder: str,
    ) -> None:
        workspace = ship_workspace.workspace
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): a (DEM-7)"])
        monkeypatch.setenv("AGENT_HUB_ROOT", str(workspace.hub))
        child_calls.clear()
        cwd = workspace.hub if folder == "hub" else workspace.ws / "demo-api"

        result = run_command(cwd, "ship")

        assert_refused(result, NOT_IN_TASK_WORKTREE)
        assert child_calls.calls == []
        assert tracker.calls == []


def both_ahead(make_task_worktree: Callable[..., Any]) -> tuple[Any, Any]:
    """``demo-api``'s ``dem-7-x`` and ``demo-web``'s ``dem-7``, one commit ahead each."""
    api = make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])
    web = make_task_worktree("demo-web", "dem-7", ["feat(web): add y (DEM-7)"])
    return api, web


def ship_live(
    ship_workspace: Workspace, run_command: CommandRunner, child_calls: Any, *arguments: str
) -> Result:
    """``hub ship DEM-7 <arguments>`` from the hub, the setup's calls forgotten first."""
    child_calls.clear()
    return run_command(ship_workspace.workspace.hub, "ship", ISSUE, *arguments)


def log_path(ship_workspace: Workspace, repo: str) -> Any:
    return ship_workspace.workspace.hub / ".agent-runs" / "ship" / f"{ISSUE}-{repo}.log"


def pushes(child_calls: Any) -> list[Any]:
    return [call for call in child_calls.calls if call.argv[0] == "git" and "push" in call.argv]


@pytest.mark.usefixtures("with_key")
class TestShipCheck:
    def test_refuses_before_checks_when_tree_dirty(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        _, web = both_ahead(make_task_worktree)
        (web / "README.md").write_text("left behind\n")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[1:] == [
            "hub ship: demo-web: uncommitted changes in the worktree",
            "hub ship: nothing was checked or pushed",
        ]
        assert "bash" not in child_calls.programs()
        assert_nothing_shipped(ship_workspace, child_calls, tracker)

    def test_runs_checks_in_order_before_push_when_both_ahead(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        api, web = both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        checks = [
            (index, call.argv, call.cwd)
            for index, call in enumerate(child_calls.calls)
            if call.argv[0] == "bash"
        ]
        assert [(argv, cwd) for _, argv, cwd in checks] == [
            (["bash", "-c", "make check"], api),
            (["bash", "-c", "make check"], web),
        ]
        assert [call["cwd"] for call in ship_workspace.calls("make")] == [str(api), str(web)]
        pushed = [
            index for index, call in enumerate(child_calls.calls) if call in pushes(child_calls)
        ]
        assert len(pushed) == 2
        assert all(checks[-1][0] < index for index in pushed)

    def test_hides_keys_from_check_when_check_runs(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        both_ahead(make_task_worktree)
        monkeypatch.setenv("GH_TOKEN", "gh-synthetic")
        monkeypatch.setenv("GITHUB_TOKEN", "github-synthetic")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        hidden = {KEY_VARIABLE, "GH_TOKEN", "GITHUB_TOKEN"}
        checks = [call for call in child_calls.calls if call.argv[0] == "bash"]
        assert len(checks) == 2
        assert all(not hidden & set(call.env) for call in checks)
        assert all(not hidden & set(call["env"]) for call in ship_workspace.calls("make"))

    def test_writes_log_when_check_runs(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])
        path = log_path(ship_workspace, "demo-api")
        path.parent.mkdir(parents=True)
        path.write_text("an older run's log, longer than the new one\n" * 50)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert path.read_bytes() == b"--- stdout ---\nsynthetic gate output\n--- stderr ---\n"
        assert path.stat().st_mode & 0o777 == 0o600

    def test_makes_private_log_folder_when_none_exists(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
        set_umask: Callable[[int], None],
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])
        set_umask(0o022)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        path = log_path(ship_workspace, "demo-api")
        assert path.stat().st_mode & 0o777 == 0o600
        for folder in (path.parent, path.parent.parent):
            assert folder.stat().st_mode & 0o777 == 0o700

    def test_stops_before_push_when_web_check_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        check = "echo synthetic web failure >&2; exit 3"
        set_check(ship_workspace.workspace.hub, "demo-web", check)
        path = log_path(ship_workspace, "demo-web")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[1:] == [
            f"hub ship: demo-web: check failed ({check}); output in {path}",
            "hub ship: nothing was pushed",
        ]
        assert path.read_bytes() == b"--- stdout ---\n--- stderr ---\nsynthetic web failure\n"
        assert [call.argv[0] for call in child_calls.calls if call.argv[0] != "git"] == [
            "bash",
            "bash",
        ]
        assert_nothing_shipped_after_checks(ship_workspace, child_calls, tracker)

    def test_fails_check_when_check_times_out(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])
        monkeypatch.setattr(run_steps, "GATE_TIMEOUT", 1.0)
        monkeypatch.setenv("FAKE_MAKE_SLEEP", "30")
        path = log_path(ship_workspace, "demo-api")

        started = time.monotonic()
        result = ship_live(ship_workspace, run_command, child_calls)

        assert time.monotonic() - started < 20
        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[1:] == [
            f"hub ship: demo-api: check failed (make check): bash timed out after 1 s;"
            f" output in {path}",
            "hub ship: nothing was pushed",
        ]
        assert path.read_bytes() == b"--- bash timed out after 1 s ---\n"
        assert_nothing_shipped_after_checks(ship_workspace, child_calls, tracker)

    def test_refuses_log_when_log_path_is_symlink(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        tmp_path: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"not the log's\n")
        path = log_path(ship_workspace, "demo-api")
        path.parent.mkdir(parents=True)
        path.symlink_to(outside)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        lines = result.stderr.splitlines()[1:]
        assert lines[0].startswith(f"hub ship: demo-api: cannot open the check log {path}: ")
        assert lines[1:] == ["hub ship: nothing was pushed"]
        assert outside.read_bytes() == b"not the log's\n"
        assert "bash" not in child_calls.programs()

    def test_refuses_log_when_log_folder_is_symlink(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        tmp_path: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])
        outside = tmp_path / "outside-folder"
        outside.mkdir()
        folder = ship_workspace.workspace.hub / ".agent-runs" / "ship"
        folder.parent.mkdir()
        folder.symlink_to(outside)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        path = log_path(ship_workspace, "demo-api")
        assert result.stderr.splitlines()[1].startswith(
            f"hub ship: demo-api: cannot open the check log {path}: "
        )
        assert list(outside.iterdir()) == []
        assert "bash" not in child_calls.programs()

    def test_refuses_push_when_check_commits(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        identity = "-c user.name=Sneak -c user.email=sneak@example.com"
        check = f"git {identity} commit --allow-empty -qm sneak && make check"
        set_check(ship_workspace.workspace.hub, "demo-web", check)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[1:] == [
            "hub ship: demo-web: the branch moved during the check; nothing was pushed"
        ]
        assert pushes(child_calls) == []
        assert_nothing_shipped_after_checks(ship_workspace, child_calls, tracker)

    def test_refuses_push_when_check_edits_tracked_file(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        set_check(ship_workspace.workspace.hub, "demo-web", "echo edit >> README.md && make check")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[1:] == [
            "hub ship: demo-web: uncommitted changes in the worktree",
            "hub ship: nothing was pushed",
        ]
        assert pushes(child_calls) == []
        assert_nothing_shipped_after_checks(ship_workspace, child_calls, tracker)

    def test_names_log_path_when_log_cannot_be_opened(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        *,
        make_task_worktree: Callable[..., Any],
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])
        folder = ship_workspace.workspace.hub / ".agent-runs" / "ship"
        folder.parent.mkdir()
        folder.write_text("not a folder\n")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        lines = result.stderr.splitlines()[1:]
        path = log_path(ship_workspace, "demo-api")
        assert lines[0].startswith(f"hub ship: demo-api: cannot open the check log {path}: ")
        assert lines[1:] == ["hub ship: nothing was pushed"]
        assert "bash" not in child_calls.programs()
        assert_nothing_shipped(ship_workspace, child_calls, tracker)


def set_check(hub: Any, repo: str, check: str) -> None:
    document = json.loads((hub / "hub.json").read_text())
    entry = next(entry for entry in document["repos"] if entry["dir"] == repo)
    entry["check"] = check
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")


def assert_nothing_shipped_after_checks(
    ship_workspace: Workspace, child_calls: Any, tracker: Any
) -> None:
    """Checks may have run, but no push, ``gh`` call or tracker write."""
    assert pushes(child_calls) == []
    assert ship_workspace.calls("gh") == []
    assert tracker.calls == [("get_issue", ISSUE)]


API_PR = "https://github.com/acme/demo-api/pull/101"
WEB_PR = "https://github.com/acme/demo-web/pull/102"
ISSUE_URL = "https://linear.app/demo/issue/DEM-7"
SHIP_BODY = f"DEM-7 {ISSUE_URL}\n\n{RELATED_START}\n## Related PRs\n{RELATED_END}"


def create_call(github: str, branch: str, title: str, *, draft: bool = False) -> list[str]:
    argv = [
        *("gh", "pr", "create", "--repo", github, "--base", "trunk", "--head", branch),
        *("--title", title, "--body", SHIP_BODY),
    ]
    return [*argv, "--draft"] if draft else argv


def shipping_calls(child_calls: Any) -> list[tuple[list[str], Any]]:
    """The token-bearing children, in order: each push and ``gh`` call, with its cwd."""
    return [
        (call.argv, call.cwd)
        for call in child_calls.calls
        if call.argv[0] == "gh" or call in pushes(child_calls)
    ]


def seeded_pr(*, state: str, url: str = "https://github.com/acme/demo-api/pull/7") -> Any:
    return {
        "repo": API_GITHUB,
        "head": "jdoe/dem-7-x",
        "base": "trunk",
        "title": "by hand",
        "url": url,
        "state": state,
        "body": "Opened by hand.",
        "draft": False,
    }


@pytest.mark.usefixtures("with_key")
class TestShipPrs:
    def test_opens_prs_in_order_when_checks_pass(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        api, web = both_ahead(make_task_worktree)
        workspace = ship_workspace.workspace

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        api_title, web_title = "feat(api): add x (DEM-7)", "feat(web): add y (DEM-7)"
        assert shipping_calls(child_calls) == [
            (["git", *push_command("jdoe/dem-7-x")[1:]], api),
            (create_call(API_GITHUB, "jdoe/dem-7-x", api_title), api),
            (["git", *push_command("jdoe/dem-7")[1:]], web),
            (create_call("acme/demo-web", "jdoe/dem-7", web_title), web),
            (["gh", "pr", "view", API_PR, "--json", "body"], api),
            (
                ["gh", "pr", "edit", API_PR, "--body-file", body_file(ship_workspace, "demo-api")],
                api,
            ),
            (["gh", "pr", "view", WEB_PR, "--json", "body"], web),
            (
                ["gh", "pr", "edit", WEB_PR, "--body-file", body_file(ship_workspace, "demo-web")],
                web,
            ),
        ]
        assert [(pr["url"], pr["draft"]) for pr in ship_workspace.prs()] == [
            (API_PR, False),
            (WEB_PR, False),
        ]
        for repo, worktree, branch in (
            ("demo-api", api, "jdoe/dem-7-x"),
            ("demo-web", web, "jdoe/dem-7"),
        ):
            pushed = workspace.git(workspace.origin(repo), "rev-parse", f"refs/heads/{branch}")
            assert pushed == workspace.git(worktree, "rev-parse", "HEAD")
        assert result.stdout.splitlines()[-2:] == [
            f"opened: demo-api  {API_PR}",
            f"opened: demo-web  {WEB_PR}",
        ]

    def test_adds_draft_when_draft_given(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls, "--draft")

        assert result.exit_code == 0, result.output
        gh = [call["argv"] for call in ship_workspace.calls("gh")]
        creates = [argv for argv in gh if argv[:2] == ["pr", "create"]]
        assert [argv[-1] for argv in creates] == ["--draft", "--draft"]
        assert [pr["draft"] for pr in ship_workspace.prs()] == [True, True]

    def test_refuses_web_push_when_credential_helper_set(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        _, web = both_ahead(make_task_worktree)
        value = "!echo synthetic-helper-value"
        ship_workspace.workspace.git(web, "config", "credential.helper", value)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert (
            "hub ship: demo-web: push failed: git config holds keys a push would use"
            " (credential.helper); the branch was not pushed"
        ) in result.stderr.splitlines()
        assert "synthetic-helper-value" not in result.output
        assert [call.cwd.name for call in pushes(child_calls)] == ["dem-7-x"]
        assert [pr["repo"] for pr in ship_workspace.prs()] == [API_GITHUB]

    def test_refuses_web_push_when_origin_not_github(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        _, web = both_ahead(make_task_worktree)
        ship_workspace.workspace.git(
            web, "config", "remote.origin.url", "https://github.com/acme/other.git"
        )

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert (
            "hub ship: demo-web: push failed: remote.origin.url is not the GitHub url of"
            " acme/demo-web; the branch was not pushed"
        ) in result.stderr.splitlines()
        assert [call.cwd.name for call in pushes(child_calls)] == ["dem-7-x"]

    def test_uses_open_pr_when_create_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        found = "https://github.com/acme/demo-api/pull/7"
        ship_workspace.write_prs([seeded_pr(state="OPEN", url=found)])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert [call["argv"][:3] for call in ship_workspace.calls("gh")] == [
            ["pr", "create", "--repo"],
            ["pr", "view", "jdoe/dem-7-x"],
            ["pr", "create", "--repo"],
            ["pr", "view", found],
            ["pr", "edit", found],
            ["pr", "view", WEB_PR],
            ["pr", "edit", WEB_PR],
        ]
        assert [pr["url"] for pr in ship_workspace.prs()] == [found, WEB_PR]
        assert result.stdout.splitlines()[-2:] == [
            f"found: demo-api  {found}",
            f"opened: demo-web  {WEB_PR}",
        ]

    def test_fails_when_found_pr_not_open(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        both_ahead(make_task_worktree)
        ship_workspace.write_prs([seeded_pr(state="CLOSED")])
        monkeypatch.setenv("FAKE_GH_FAIL", "create:demo-api")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert (
            "hub ship: demo-api: pull request failed: gh pr create failed:"
            " gh (fake): synthetic create failure"
        ) in result.stderr.splitlines()
        assert [call.cwd.name for call in pushes(child_calls)] == ["dem-7-x"]

    def test_fails_when_gh_prints_no_url(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        both_ahead(make_task_worktree)
        monkeypatch.setenv("FAKE_GH_FAIL", "nourl:demo-api")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert "hub ship: demo-api: pull request failed: gh printed no PR url" in (
            result.stderr.splitlines()
        )
        assert ship_workspace.prs() == []


def pr_titles(ship_workspace: Workspace) -> list[str]:
    return [pr["title"] for pr in ship_workspace.prs()]


@pytest.mark.usefixtures("with_key")
class TestShipTitle:
    def test_titles_pr_from_newest_commit_when_two_ahead(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree(
            "demo-api", "dem-7-x", ["feat(api): add x (DEM-7)", "fix(api): y (DEM-7)"]
        )

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert pr_titles(ship_workspace) == ["fix(api): y (DEM-7)"]

    def test_warns_once_when_subject_unmatched_in_mixed_hub(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        use_mixed_hub(ship_workspace)
        make_task_worktree("demo-api", "dem-7-x", ["DEM-7: feat(api): add x"])
        make_task_worktree("demo-web", "dem-7-x", ["feat(web): add y (DEM-7)"])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert pr_titles(ship_workspace) == ["DEM-7: feat(api): add x", "feat(web): add y (DEM-7)"]
        warning = (
            "hub ship: warning: the commit subject `feat(web): add y (DEM-7)` does not match"
            " commit_title `{ISSUE}: {type}({scope}): {summary}`; the PR title is the subject"
        )
        assert [line for line in result.stderr.splitlines() if "warning" in line] == [warning]

    def test_holds_issue_and_empty_section_when_body_built(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert [pr["body"] for pr in ship_workspace.prs()] == [SHIP_BODY]
        assert SHIP_BODY.count(RELATED_START) == SHIP_BODY.count(RELATED_END) == 1


NOT_LINKED = "hub ship: no PR was linked and the issue was not moved"


def reject_pushes(ship_workspace: Workspace, repo: str) -> None:
    """A pre-receive hook in ``repo``'s origin that refuses every push."""
    hook = ship_workspace.workspace.origin(repo) / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho synthetic rejection >&2\nexit 1\n")
    hook.chmod(0o755)


def assert_unlinked(ship_workspace: Workspace, tracker: Any) -> None:
    """No PR body read or edited, no tracker write."""
    gh = [call["argv"] for call in ship_workspace.calls("gh")]
    assert gh != []
    assert [argv for argv in gh if argv[:2] == ["pr", "edit"] or "body" in argv] == []
    assert tracker.calls == [("get_issue", ISSUE)]


@pytest.mark.usefixtures("with_key")
class TestShipPartial:
    def test_lists_open_pr_when_web_push_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        reject_pushes(ship_workspace, "demo-web")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        lines = result.stderr.splitlines()
        assert lines[-3].startswith("hub ship: demo-web: push failed: ")
        assert "push failed: push failed" not in result.stderr
        assert "synthetic rejection" in lines[-3]
        assert lines[-2:] == [f"hub ship: PR open: {API_PR}", NOT_LINKED]
        assert [pr["url"] for pr in ship_workspace.prs()] == [API_PR]
        assert_unlinked(ship_workspace, tracker)

    def test_names_pull_request_step_when_web_pr_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        both_ahead(make_task_worktree)
        monkeypatch.setenv("FAKE_GH_FAIL", "create:demo-web,view:demo-web")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[-3:] == [
            "hub ship: demo-web: pull request failed: gh pr create failed:"
            " gh (fake): synthetic create failure",
            f"hub ship: PR open: {API_PR}",
            NOT_LINKED,
        ]
        assert [call.cwd.name for call in pushes(child_calls)] == ["dem-7-x", "dem-7"]
        assert_unlinked(ship_workspace, tracker)

    def test_finishes_without_duplicates_when_run_again(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        reject_pushes(ship_workspace, "demo-web")
        failed = ship_live(ship_workspace, run_command, child_calls)
        assert failed.exit_code == 1, failed.output
        (ship_workspace.workspace.origin("demo-web") / "hooks" / "pre-receive").unlink()

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[-2:] == [
            f"found: demo-api  {API_PR}",
            f"opened: demo-web  {WEB_PR}",
        ]
        assert [(pr["repo"], pr["url"]) for pr in ship_workspace.prs()] == [
            (API_GITHUB, API_PR),
            ("acme/demo-web", WEB_PR),
        ]
        assert [pr["body"] for pr in ship_workspace.prs()] == [
            linked_body(WEB_PR),
            linked_body(API_PR),
        ]
        assert tracker.calls == [
            ("get_issue", ISSUE),
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "In Review"),
            ("comment", ISSUE, f"Pull requests:\n- {API_PR}\n- {WEB_PR}"),
        ]


def body_file(ship_workspace: Workspace, repo: str) -> str:
    """The body file ``gh pr edit --body-file`` gets for ``repo``."""
    return str(log_path(ship_workspace, repo).with_suffix(".body"))


def linked_body(*urls: str, before: str = f"DEM-7 {ISSUE_URL}\n\n") -> str:
    """A shipped PR's body whose Related PRs section lists ``urls``."""
    listed = "".join(f"- {url}\n" for url in urls)
    return f"{before}{RELATED_START}\n## Related PRs\n{listed}{RELATED_END}"


def link_calls(ship_workspace: Workspace) -> list[list[str]]:
    """The ``gh`` calls of the link phase: each body read and each edit."""
    return [
        call["argv"]
        for call in ship_workspace.calls("gh")
        if call["argv"][:2] == ["pr", "edit"] or call["argv"][-2:] == ["--json", "body"]
    ]


@pytest.mark.usefixtures("with_key")
class TestShipLinks:
    def test_lists_other_pr_when_two_prs_open(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        api, web = both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert link_calls(ship_workspace) == [
            ["pr", "view", API_PR, "--json", "body"],
            ["pr", "edit", API_PR, "--body-file", body_file(ship_workspace, "demo-api")],
            ["pr", "view", WEB_PR, "--json", "body"],
            ["pr", "edit", WEB_PR, "--body-file", body_file(ship_workspace, "demo-web")],
        ]
        assert [call.cwd for call in child_calls.calls if call.argv[0] == "gh"][-4:] == [
            api,
            api,
            web,
            web,
        ]
        assert [pr["body"] for pr in ship_workspace.prs()] == [
            linked_body(WEB_PR),
            linked_body(API_PR),
        ]

    def test_skips_links_when_one_pr_shipped(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert [call["argv"][:2] for call in ship_workspace.calls("gh")] == [["pr", "create"]]
        assert link_calls(ship_workspace) == []
        assert [pr["body"] for pr in ship_workspace.prs()] == [SHIP_BODY]

    def test_keeps_outside_text_when_body_edited(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        found = "https://github.com/acme/demo-api/pull/7"
        before, after = "Notes by hand.\n  indented, trailing  \n\n", "\n\nA footer by hand.\n"
        stale = (
            f"{RELATED_START}\n## Related PRs\n- https://github.com/acme/old/pull/1\n{RELATED_END}"
        )
        ship_workspace.write_prs(
            [seeded_pr(state="OPEN", url=found) | {"body": before + stale + after}]
        )

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        api_body, web_body = (pr["body"] for pr in ship_workspace.prs())
        assert api_body == linked_body(WEB_PR, before=before) + after
        assert web_body == linked_body(found)

    def test_appends_section_once_when_found_body_lacks_markers(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        found = "https://github.com/acme/demo-api/pull/7"
        ship_workspace.write_prs([seeded_pr(state="OPEN", url=found)])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        api_body = ship_workspace.prs()[0]["body"]
        assert api_body == linked_body(WEB_PR, before="Opened by hand.\n\n")
        assert api_body.count(RELATED_START) == api_body.count(RELATED_END) == 1

    def test_skips_edit_when_run_again_unchanged(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        first = ship_live(ship_workspace, run_command, child_calls)
        assert first.exit_code == 0, first.output
        linked = ship_workspace.prs()
        ship_workspace.logs.joinpath("gh.jsonl").unlink()

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert link_calls(ship_workspace) == [
            ["pr", "view", API_PR, "--json", "body"],
            ["pr", "view", WEB_PR, "--json", "body"],
        ]
        assert ship_workspace.prs() == linked
        for pr in ship_workspace.prs():
            assert pr["body"].count(RELATED_START) == pr["body"].count(RELATED_END) == 1

    @pytest.mark.parametrize(
        ("fails", "body", "suffix"),
        [
            ("body:demo-api", None, ": gh (fake): synthetic body failure"),
            ("", 7, ""),
            ("", "x" * (1 << 20), ""),
        ],
        ids=["gh-fails", "not-text", "too-long"],
    )
    def test_fails_link_step_when_body_unreadable(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
        fails: str,
        body: Any,
        suffix: str,
    ) -> None:
        both_ahead(make_task_worktree)
        api = API_PR
        if body is not None:
            api = "https://github.com/acme/demo-api/pull/7"
            ship_workspace.write_prs([seeded_pr(state="OPEN", url=api) | {"body": body}])
        monkeypatch.setenv("FAKE_GH_FAIL", fails)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[-4:] == [
            f"hub ship: demo-api: link failed: could not read the body of {api}{suffix}",
            f"hub ship: PR open: {api}",
            f"hub ship: PR open: {WEB_PR}",
            "hub ship: the issue was not moved",
        ]
        assert [argv for argv in link_calls(ship_workspace) if argv[1] == "edit"] == []
        reads = [call for call in child_calls.calls if call.argv[-2:] == ["--json", "body"]]
        assert [call.output_limit for call in reads] == [1_048_576]
        assert ship_steps.PR_BODY_OUTPUT_LIMIT == 1_048_576
        assert tracker.calls == [("get_issue", ISSUE)]

    def test_fails_link_step_when_edit_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        both_ahead(make_task_worktree)
        monkeypatch.setenv("FAKE_GH_FAIL", "edit:demo-web")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[-4:] == [
            "hub ship: demo-web: link failed: gh pr edit failed: gh (fake): synthetic edit failure",
            f"hub ship: PR open: {API_PR}",
            f"hub ship: PR open: {WEB_PR}",
            "hub ship: the issue was not moved",
        ]
        assert [pr["body"] for pr in ship_workspace.prs()] == [linked_body(WEB_PR), SHIP_BODY]
        assert not os.path.lexists(body_file(ship_workspace, "demo-web"))
        assert tracker.calls == [("get_issue", ISSUE)]


SHIP_COMMENT = f"Pull requests:\n- {API_PR}\n- {WEB_PR}"


@pytest.mark.usefixtures("with_key")
class TestShipTracker:
    def test_moves_then_comments_when_ship_succeeds(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert tracker.calls == [
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "In Review"),
            ("comment", ISSUE, SHIP_COMMENT),
        ]
        assert "agent" not in SHIP_COMMENT.lower()
        assert tracker.backend.issues[ISSUE].state == "In Review"

    def test_removes_failed_label_when_issue_carries_it(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        tracker_backend_for_ship: Callable[..., Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The conftest's recording tracker, over a backend whose DEM-7 carries the label.
        failed = type(tracker)(tracker_backend_for_ship(failed=True))
        monkeypatch.setattr(ship_command, "resolve_tracker_client", Resolve(failed))
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert failed.calls == [
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "In Review"),
            ("remove_label", ISSUE, "agent-failed"),
            ("comment", ISSUE, SHIP_COMMENT),
        ]
        assert "agent-failed" not in failed.backend.issues[ISSUE].labels

    def test_removes_blocked_label_when_issue_carries_it(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        tracker_backend_for_ship: Callable[..., Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ADR 0030: a delivered issue keeps no outcome label, the configured blocked one too.
        hub_file = ship_workspace.workspace.hub / "hub.json"
        document = json.loads(hub_file.read_text())
        document["tracker"]["blocked_label"] = "agent-blocked"
        hub_file.write_text(json.dumps(document, indent=2) + "\n")
        backend = tracker_backend_for_ship(failed=True)
        backend.workspace_labels = (*backend.workspace_labels, "agent-blocked")
        issue = backend.issues[ISSUE]
        backend.issues[ISSUE] = issue.model_copy(
            update={"labels": (*issue.labels, "agent-blocked")}
        )
        blocked = type(tracker)(backend)
        monkeypatch.setattr(ship_command, "resolve_tracker_client", Resolve(blocked))
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert blocked.calls == [
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "In Review"),
            ("remove_label", ISSUE, "agent-failed"),
            ("remove_label", ISSUE, "agent-blocked"),
            ("comment", ISSUE, SHIP_COMMENT),
        ]
        assert {"agent-failed", "agent-blocked"}.isdisjoint(blocked.backend.issues[ISSUE].labels)

    def test_uses_configured_review_state_when_states_set(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        tracker_backend_for_ship: Callable[..., Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The team has "Code Review" and no "In Review": a move to "In Review" would fail.
        coded = type(tracker)(tracker_backend_for_ship(states=("Todo", "Code Review")))
        monkeypatch.setattr(ship_command, "resolve_tracker_client", Resolve(coded))
        hub = ship_workspace.workspace.hub
        document = json.loads((hub / "hub.json").read_text())
        document["tracker"]["states"] = {"review": "Code Review"}
        (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
        both_ahead(make_task_worktree)

        dry = run_command(hub, "ship", ISSUE, "--dry-run")
        result = ship_live(ship_workspace, run_command, child_calls)

        assert dry.exit_code == 0, dry.output
        assert f"would call: move_state({ISSUE}, Code Review)" in dry.stdout.splitlines()
        assert result.exit_code == 0, result.output
        assert coded.calls == [
            ("get_issue", ISSUE),
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "Code Review"),
            ("comment", ISSUE, SHIP_COMMENT),
        ]
        assert coded.backend.issues[ISSUE].state == "Code Review"


NO_RETRY_WORDS = ("retry", "try again", "run again", "re-run")
COMMENT_LINE = json.dumps(f"comment({ISSUE}, {SHIP_COMMENT})")
NOT_DONE_COMMENT = f"hub ship: not done: {COMMENT_LINE}"
UNCONFIRMED = " (check the issue in the tracker)"


def assert_no_retry_advice(result: Result) -> None:
    shown = result.stderr.lower()
    assert [word for word in NO_RETRY_WORDS if word in shown] == []


@pytest.mark.usefixtures("with_key")
class TestShipTrackerFailures:
    def test_says_not_moved_when_move_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        tracker.fail_on.add("move_state")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert tracker.calls == [("get_issue", ISSUE), ("move_state", ISSUE, "In Review")]
        assert result.stderr.splitlines()[-6:] == [
            "hub ship: move_state DEM-7: synthetic outage",
            f"hub ship: PR open: {API_PR}",
            f"hub ship: PR open: {WEB_PR}",
            "hub ship: the issue may not have been moved to In Review",
            f"hub ship: not confirmed: move_state(DEM-7, In Review){UNCONFIRMED}",
            NOT_DONE_COMMENT,
        ]
        assert_no_retry_advice(result)

    def test_omits_not_moved_when_comment_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        tracker.fail_on.add("comment")

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 1, result.output
        assert tracker.calls == [
            ("get_issue", ISSUE),
            ("move_state", ISSUE, "In Review"),
            ("comment", ISSUE, SHIP_COMMENT),
        ]
        assert result.stderr.splitlines()[-4:] == [
            "hub ship: comment DEM-7: synthetic outage",
            f"hub ship: PR open: {API_PR}",
            f"hub ship: PR open: {WEB_PR}",
            f"hub ship: not confirmed: {COMMENT_LINE}{UNCONFIRMED}",
        ]
        assert "not moved" not in result.stderr
        assert "moved to" not in result.stderr
        assert "not done" not in result.stderr
        assert_no_retry_advice(result)


CO_AUTHOR = "Co-Authored-By: Claude <noreply@anthropic.com>"
GENERATED = "Generated with [Claude Code](https://claude.com/claude-code)"
ROBOT_LINE = "\N{ROBOT FACE} synthetic change"


def workspace_paths(ship_workspace: Workspace) -> set[str]:
    ws = ship_workspace.workspace.ws
    return {str(ws), os.path.realpath(ws)}


def shipped_texts(ship_workspace: Workspace, tracker: Any) -> list[str]:
    """Every text hub ship gave ``gh`` or the tracker: each ``gh`` argument but a body file's
    path (its text is the stored body), each PR's title and body as the fake stored them, and
    each write's values."""
    gh = []
    for call in ship_workspace.calls("gh"):
        argv = call["argv"]
        gh += [arg for index, arg in enumerate(argv) if argv[index - 1 : index] != ["--body-file"]]
    stored = [pr[field] for pr in ship_workspace.prs() for field in ("title", "body")]
    written = [value for _, *values in tracker.calls[1:] for value in values]
    return [*gh, *stored, *written]


def assert_no_attribution(ship_workspace: Workspace, tracker: Any) -> None:
    texts = shipped_texts(ship_workspace, tracker)
    lines = [line for text in texts for line in text.split("\n")]
    assert [line for line in lines if any(shape.matches(line) for shape in ATTRIBUTIONS)] == []
    assert [text for text in texts if ROBOT in text] == []
    paths = workspace_paths(ship_workspace)
    assert [text for text in texts if any(path in text for path in paths)] == []


@pytest.mark.usefixtures("with_key")
class TestShipAttribution:
    @pytest.mark.parametrize(
        "subject",
        [
            f"feat(api): add x {CO_AUTHOR}",
            f"feat(api): add x {GENERATED}",
            f"feat(api): add x {ROBOT_LINE}",
            "feat(api): edit {ws}/demo-api/x.py (DEM-7)",
        ],
        ids=["co-author", "generated", "robot", "workspace-path"],
    )
    def test_strips_attribution_when_subjects_carry_it(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        subject: str,
    ) -> None:
        ws = os.path.realpath(ship_workspace.workspace.ws)
        make_task_worktree("demo-api", "dem-7-x", [subject.replace("{ws}", ws)])
        make_task_worktree("demo-web", "dem-7", ["feat(web): add y (DEM-7)"])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert [call[0] for call in tracker.calls] == ["get_issue", "move_state", "comment"]
        assert_no_attribution(ship_workspace, tracker)

    def test_strips_attribution_when_found_body_carries_it(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        ws = os.path.realpath(ship_workspace.workspace.ws)
        found = "https://github.com/acme/demo-api/pull/7"
        body = f"Notes.\n{CO_AUTHOR}\n{GENERATED}\n{ROBOT_LINE}\nsee {ws}/demo-api/x.py\n"
        ship_workspace.write_prs([seeded_pr(state="OPEN", url=found) | {"body": body}])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        edits = [argv for argv in link_calls(ship_workspace) if argv[1] == "edit"]
        assert edits[0] == [
            "pr",
            "edit",
            found,
            "--body-file",
            body_file(ship_workspace, "demo-api"),
        ]
        assert ship_workspace.prs()[0]["body"] == linked_body(
            WEB_PR, before="Notes.\nsee demo-api/x.py\n\n\n"
        )
        assert_no_attribution(ship_workspace, tracker)

    def test_falls_back_to_issue_id_when_subject_only_attribution(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        make_task_worktree("demo-api", "dem-7-x", [CO_AUTHOR])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert pr_titles(ship_workspace) == [ISSUE]
        assert_no_attribution(ship_workspace, tracker)


def synthetic_token() -> str:
    return "gh" + "p_" + "y" * 36


def child_kind(argv: list[str]) -> str:
    """``check``, ``push``, ``gh`` or ``git`` (a read)."""
    if argv[0] == "bash":
        return "check"
    if argv[0] == "git" and "push" in argv:
        return "push"
    return argv[0]


@pytest.mark.usefixtures("with_key")
class TestShipProcesses:
    def test_keeps_children_in_caller_group_when_shipped(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert {child_kind(call.argv) for call in child_calls.calls} == {
            "check",
            "push",
            "gh",
            "git",
        }
        assert {call.own_session for call in child_calls.calls} == {False}
        assert {call["pgid"] for call in ship_workspace.calls("gh")} == {os.getpgid(0)}

    def test_uses_step_timeouts_when_children_run(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        timeouts = {(child_kind(call.argv), call.timeout) for call in child_calls.calls}
        assert timeouts == {("check", 1_800), ("push", 300), ("gh", 120), ("git", 120)}

    def test_scopes_tokens_when_children_run(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        both_ahead(make_task_worktree)
        monkeypatch.setenv("GH_TOKEN", synthetic_token())

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        assert [call.argv for call in child_calls.calls if KEY_VARIABLE in call.env] == []
        with_token = {child_kind(call.argv) for call in child_calls.calls if "GH_TOKEN" in call.env}
        assert with_token == {"push", "gh"}
        assert all(
            "GH_TOKEN" in call.env
            for call in child_calls.calls
            if child_kind(call.argv) in {"push", "gh"}
        )

    def test_hides_tokens_from_hub_checkout_read_when_run_from_hub_worktree(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        both_ahead(make_task_worktree)
        workspace = ship_workspace.workspace
        hub = workspace.hub
        # The hub as a repo, run from a worktree of it: git finds the main checkout first.
        workspace.git(hub, "init", "-q")
        workspace.git(hub, "add", "-A")
        workspace.git(hub, "commit", "-q", "-m", "hub")
        linked = hub.parent.parent / "hub-linked"
        workspace.git(hub, "worktree", "add", "-q", str(linked))
        monkeypatch.setenv("AGENT_HUB_ROOT", str(linked))
        monkeypatch.setenv("GH_TOKEN", synthetic_token())
        monkeypatch.setenv("GITHUB_TOKEN", synthetic_token())
        child_calls.clear()

        result = run_command(linked, "ship", ISSUE, "--dry-run")

        assert result.exit_code == 0, result.output
        checkout = [call for call in child_calls.calls if "--git-common-dir" in call.argv]
        assert [call.cwd for call in checkout] == [linked]
        hidden = {KEY_VARIABLE, "GH_TOKEN", "GITHUB_TOKEN"}
        assert [call.argv for call in child_calls.calls if hidden & call.env.keys()] == []

    def test_never_shows_secret_values_when_shipped(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        both_ahead(make_task_worktree)
        monkeypatch.setenv("GH_TOKEN", synthetic_token())

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        logs = [log_path(ship_workspace, repo) for repo in ("demo-api", "demo-web")]
        shown = [
            result.stdout,
            result.stderr,
            *(path.read_text() for path in logs),
            ship_workspace.state.read_text(),
            *(value for _, *values in tracker.calls for value in values),
        ]
        for secret in (synthetic_key(), synthetic_token()):
            assert [text for text in shown if secret in text] == []
        # The control: the token did reach the children that need it.
        given = [call for call in child_calls.calls if child_kind(call.argv) in {"push", "gh"}]
        assert given != []
        assert {call.env.get("GH_TOKEN") for call in given} == {synthetic_token()}


# One argv string longer than this fails on Linux (MAX_ARG_STRLEN, 32 pages) with E2BIG.
MAX_ARGUMENT_BYTES = 131_071


@pytest.mark.usefixtures("with_key")
class TestShipLongBodies:
    def test_edits_by_file_when_found_body_exceeds_argument_limit(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)
        found = "https://github.com/acme/demo-api/pull/7"
        long_body = "\N{CJK UNIFIED IDEOGRAPH-4E2D}" * 43_691
        ship_workspace.write_prs([seeded_pr(state="OPEN", url=found) | {"body": long_body}])

        result = ship_live(ship_workspace, run_command, child_calls)

        assert result.exit_code == 0, result.output
        expected = linked_body(WEB_PR, before=long_body + "\n\n")
        assert len(expected.encode()) > MAX_ARGUMENT_BYTES
        assert ship_workspace.prs()[0]["body"] == expected
        longest = max(len(argument.encode()) for c in child_calls.calls for argument in c.argv)
        assert longest <= MAX_ARGUMENT_BYTES
        edits = [call["argv"] for call in ship_workspace.calls("gh") if call["argv"][1] == "edit"]
        assert edits == [
            ["pr", "edit", found, "--body-file", body_file(ship_workspace, "demo-api")],
            ["pr", "edit", WEB_PR, "--body-file", body_file(ship_workspace, "demo-web")],
        ]
        folder = log_path(ship_workspace, "demo-api").parent
        assert sorted(entry.name for entry in folder.iterdir()) == [
            "DEM-7-demo-api.log",
            "DEM-7-demo-web.log",
        ]


DRY_API_PR = "<PR url of demo-api>"
DRY_WEB_PR = "<PR url of demo-web>"
GIT_READS = {"branch", "rev-list", "log"}


def git_subcommand(argv: list[str]) -> str:
    """The git subcommand of ``argv``: the first argument after the ``-c`` options."""
    rest = argv[1:]
    while rest[0] == "-c":
        rest = rest[2:]
    return rest[0]


@pytest.mark.usefixtures("with_key")
class TestShipDryRun:
    def test_prints_children_and_writes_when_dry_run(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        api, web = both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls, "--dry-run")

        assert result.exit_code == 0, result.output
        api_title, web_title = "feat(api): add x (DEM-7)", "feat(web): add y (DEM-7)"
        assert result.stdout.splitlines() == [
            "ship: demo-api  jdoe/dem-7-x",
            "ship: demo-web  jdoe/dem-7",
            f"would run: bash -c 'make check'   (cwd {api})",
            f"would run: {shown_command(push_command('jdoe/dem-7-x'))}   (cwd {api})",
            f"would run: {shown_command(create_call(API_GITHUB, 'jdoe/dem-7-x', api_title))}"
            f"   (cwd {api})",
            f"would run: bash -c 'make check'   (cwd {web})",
            f"would run: {shown_command(push_command('jdoe/dem-7'))}   (cwd {web})",
            f"would run: {shown_command(create_call('acme/demo-web', 'jdoe/dem-7', web_title))}"
            f"   (cwd {web})",
            f"would call: move_state({ISSUE}, In Review)",
            "would call: "
            + json.dumps(f"comment({ISSUE}, Pull requests:\n- {DRY_API_PR}\n- {DRY_WEB_PR})"),
        ]

    def test_adds_draft_when_dry_run_draft(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        api = make_task_worktree("demo-api", "dem-7-x", ["feat(api): add x (DEM-7)"])

        result = ship_live(ship_workspace, run_command, child_calls, "--dry-run", "--draft")

        assert result.exit_code == 0, result.output
        creates = [line for line in result.stdout.splitlines() if " gh pr create " in line]
        draft = create_call(API_GITHUB, "jdoe/dem-7-x", "feat(api): add x (DEM-7)", draft=True)
        assert creates == [f"would run: {shown_command(draft)}   (cwd {api})"]
        # A dry run never shows a link edit: the live one runs only when it changes a body.
        assert " gh pr edit " not in result.stdout

    def test_prints_label_removal_when_dry_run_issue_carries_failed_label(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        tracker_backend_for_ship: Callable[..., Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The conftest's recording tracker, over a backend whose DEM-7 carries the label.
        failed = type(tracker)(tracker_backend_for_ship(failed=True))
        monkeypatch.setattr(ship_command, "resolve_tracker_client", Resolve(failed))
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls, "--dry-run")

        assert result.exit_code == 0, result.output
        calls = [line for line in result.stdout.splitlines() if line.startswith("would call: ")]
        assert calls == [
            f"would call: move_state({ISSUE}, In Review)",
            f"would call: remove_label({ISSUE}, agent-failed)",
            "would call: "
            + json.dumps(f"comment({ISSUE}, Pull requests:\n- {DRY_API_PR}\n- {DRY_WEB_PR})"),
        ]
        assert failed.calls == [("get_issue", ISSUE)]
        assert "agent-failed" in failed.backend.issues[ISSUE].labels

    def test_names_repo_when_dry_run_title_read_fails(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        api, web = both_ahead(make_task_worktree)
        real = ship_steps.run_child

        # demo-web's git log -1 fails as git does on a broken object; every other child runs.
        def failing_log(argv: list[str], **options: Any) -> ChildResult:
            if argv[1:2] == ["log"] and os.path.samefile(options["cwd"], web):
                return ChildResult(128, b"", b"fatal: bad object HEAD\n")
            return real(argv, **options)

        monkeypatch.setattr(ship_steps, "run_child", failing_log)

        result = ship_live(ship_workspace, run_command, child_calls, "--dry-run")

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[-1] == (
            "hub ship: demo-web: git log failed: fatal: bad object HEAD"
        )
        shown = result.stdout.splitlines()
        assert [line for line in shown if line.endswith(f"(cwd {web})")] == []
        assert len([line for line in shown if line.endswith(f"(cwd {api})")]) == 3
        assert [line for line in shown if line.startswith("would call: ")] == []
        assert tracker.calls == [("get_issue", ISSUE)]

    def test_reads_issue_once_when_dry_run(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls, "--dry-run")

        assert result.exit_code == 0, result.output
        assert tracker.calls == [("get_issue", ISSUE)]
        assert tracker.backend.issues[ISSUE].state != "In Review"

    def test_runs_only_git_reads_when_dry_run(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
    ) -> None:
        both_ahead(make_task_worktree)

        result = ship_live(ship_workspace, run_command, child_calls, "--dry-run")

        assert result.exit_code == 0, result.output
        assert set(child_calls.programs()) == {"git"}
        assert {git_subcommand(call.argv) for call in child_calls.calls} <= GIT_READS
        assert "log" in {git_subcommand(call.argv) for call in child_calls.calls}
        for tool in ("gh", "make"):
            assert ship_workspace.calls(tool) == []
        assert ship_workspace.prs() == []

    def test_leaves_workspace_unchanged_when_dry_run(
        self,
        ship_workspace: Workspace,
        run_command: CommandRunner,
        make_task_worktree: Callable[..., Any],
        *,
        tracker: Any,
        child_calls: Any,
        tree_digest: Callable[..., Any],
    ) -> None:
        api, web = both_ahead(make_task_worktree)
        # Stale stat data: a read that may refresh the index (git status) would rewrite it.
        for worktree in (api, web):
            tracked_files = list(worktree.glob("*.md"))
            assert tracked_files != [], worktree
            for tracked in tracked_files:
                os.utime(tracked, (time.time() + 5, time.time() + 5))
        workspace = ship_workspace.workspace.hub.parent
        before = tree_digest(workspace)

        result = ship_live(ship_workspace, run_command, child_calls, "--dry-run")

        assert result.exit_code == 0, result.output
        assert tree_digest(workspace) == before
        assert not (ship_workspace.workspace.hub / ".agent-runs" / "ship").exists()
        assert not log_path(ship_workspace, "demo-api").exists()
