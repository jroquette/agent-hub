"""``hub worktree``: isolated worktrees for one task in every repo of the hub (AC-15.1 to AC-15.4).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``): the hub at
``ws/hub`` with default branch ``trunk``, ``demo-api`` and ``demo-web`` cloned next to it from
local bare origins, each origin one commit ahead of its clone, so a skipped fetch shows.
"""

from collections.abc import Callable
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

REPOS = ("demo-api", "demo-web")
NAME = "dem-7-x"
BRANCH = "jdoe/dem-7-x"
SHAPE = "name must be the issue, dem-<n>[-<desc>] (e.g. dem-7-collector)"
# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"


def assert_refused(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout."""
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "Usage: hub worktree" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if message in text] == [message], shown


def assert_untouched(workspace: Workspace) -> None:
    """Nothing fetched (no ``FETCH_HEAD``, ``origin/trunk`` as cloned) and nothing created."""
    for repo in REPOS:
        checkout = workspace.ws / repo
        assert not (checkout / ".git" / "FETCH_HEAD").exists()
        assert workspace.git(checkout, "rev-parse", "origin/trunk") == workspace.git(
            checkout, "rev-parse", "HEAD"
        )
        assert not (checkout / ".claude").exists()


def summary(name: str, repos: str, remove: str) -> list[str]:
    return ["", f"task     : {name} (branch jdoe/{name})", f"repos    : {repos}", remove]


class TestUsage:
    def test_lists_name_only_and_remove_when_help_requested(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", "--help", env={"COLUMNS": "120"})

        assert result.exit_code == 0
        shown = unstyle(result.stdout)
        for text in ("NAME", "--only", "REPO", "--remove"):
            assert text in shown

    def test_refuses_when_name_missing(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree")

        assert_refused(result, "Missing argument 'NAME'.")
        assert_untouched(demo_workspace)

    def test_refuses_when_option_unknown(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", NAME, "--nope")

        assert_refused(result, "No such option: --nope")
        assert_untouched(demo_workspace)

    @pytest.mark.parametrize("name", ["DEM-7", "dem7", "xyz-7", "dem-7/x"])
    def test_refuses_name_when_shape_wrong(
        self, demo_workspace: Workspace, run_command: CommandRunner, name: str
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", name)

        assert_refused(result, SHAPE)
        assert_untouched(demo_workspace)

    def test_refuses_name_when_ref_format_refused(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", "dem-7-a..b")

        assert_refused(
            result,
            "git refuses the branch name jdoe/dem-7-a..b; use a name like dem-7-collector",
        )
        assert_untouched(demo_workspace)

    def test_refuses_when_only_unknown(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", NAME, "--only", "nope")

        assert_refused(result, "unknown repo in --only: nope; use one of: demo-api demo-web")
        assert_untouched(demo_workspace)

    def test_exits_two_when_not_a_hub(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.ws, "worktree", NAME)

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{demo_workspace.ws}: not a hub: no hub.json in this folder"
            " (hub worktree runs in the hub folder or through ./hub)\n"
        )
        assert_untouched(demo_workspace)

    def test_prints_reader_lines_when_hub_json_invalid(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        (demo_workspace.hub / "hub.json").write_bytes(b"{}\n")

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 1
        assert result.stdout == ""
        lines = result.stderr.splitlines()
        assert lines
        assert all(line.startswith("hub.json: ") for line in lines), lines
        assert_untouched(demo_workspace)


class TestCreate:
    def test_creates_worktrees_from_fetched_base_when_name_valid(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        advanced = {repo: demo_workspace.origin_head(repo) for repo in REPOS}

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            *(
                f"created  {demo_workspace.worktree(repo, NAME)} ({BRANCH} from origin/trunk)"
                for repo in REPOS
            ),
            *summary(NAME, "demo-api demo-web", f"remove   : ./hub worktree --remove {NAME}"),
        ]
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "branch", "--show-current") == BRANCH
            assert demo_workspace.git(worktree, "rev-parse", "HEAD") == advanced[repo]

    def test_prints_exists_without_fetch_when_rerun(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        assert run_command(demo_workspace.hub, "worktree", NAME).exit_code == 0
        heads = {
            repo: demo_workspace.git(demo_workspace.worktree(repo, NAME), "rev-parse", "HEAD")
            for repo in REPOS
        }
        fetched = {
            repo: (demo_workspace.ws / repo / ".git" / "FETCH_HEAD").stat().st_mtime_ns
            for repo in REPOS
        }
        for repo in REPOS:
            demo_workspace.advance(repo)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            *(f"exists   {demo_workspace.worktree(repo, NAME)}" for repo in REPOS),
            *summary(NAME, "demo-api demo-web", f"remove   : ./hub worktree --remove {NAME}"),
        ]
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "rev-parse", "HEAD") == heads[repo]
            fetch_head = demo_workspace.ws / repo / ".git" / "FETCH_HEAD"
            assert fetch_head.stat().st_mtime_ns == fetched[repo]

    def test_checks_out_existing_branch_when_branch_present(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        checkout = demo_workspace.ws / "demo-api"
        demo_workspace.git(checkout, "branch", BRANCH)
        kept = demo_workspace.git(checkout, "rev-parse", BRANCH)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        worktree = demo_workspace.worktree("demo-api", NAME)
        assert demo_workspace.git(worktree, "branch", "--show-current") == BRANCH
        assert demo_workspace.git(worktree, "rev-parse", "HEAD") == kept
        assert kept != demo_workspace.origin_head("demo-api")

    def test_touches_one_repo_when_only_given(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-api")

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            f"created  {demo_workspace.worktree('demo-api', NAME)} ({BRANCH} from origin/trunk)",
            *summary(
                NAME, "demo-api", f"remove   : ./hub worktree --remove {NAME} --only demo-api"
            ),
        ]
        web = demo_workspace.ws / "demo-web"
        assert not (web / ".git" / "FETCH_HEAD").exists()
        assert not (web / ".claude").exists()
