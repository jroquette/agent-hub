"""``hub ship``'s shipping set (AC-63.4 to AC-63.6, E2, E4, E8), found by function.

Every case runs in a copy of the ``DEMO`` workspace (``demo_workspace``): the hub at ``ws/hub``,
``demo-api`` and ``demo-web`` cloned next to it from local bare origins, default branch
``trunk``, branch prefix ``jdoe/``. Task worktrees are made by ``hub worktree <name> --only
<repo>`` (from a freshly fetched ``origin/trunk``), then given empty commits.
"""

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.cli import ship_set
from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.errors import ShipError
from agent_hub.cli.hub_config_reader import load_hub_config_or_exit
from agent_hub.cli.ship_set import ShipSet, issue_from_cwd, shipping_set
from agent_hub.core.testing.builders import a_conventions_document

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

ISSUE = "DEM-7"
PREFIX = "jdoe/"


def make_task_worktree(
    workspace: Workspace, run_command: CommandRunner, *, repo: str, name: str, commits: int
) -> Path:
    """``hub worktree <name> --only <repo>``, then ``commits`` empty commits in it."""
    result = run_command(workspace.hub, "worktree", name, "--only", repo)
    assert result.exit_code == 0, result.output
    worktree: Path = workspace.worktree(repo, name)
    for number in range(commits):
        workspace.git(worktree, "commit", "--allow-empty", "-q", "-m", f"change {number}")
    return worktree


def ship_set_of(workspace: Workspace, issue_id: str = ISSUE) -> ShipSet:
    config = load_hub_config_or_exit(workspace.hub / "hub.json")
    return shipping_set(
        config,
        workspace=workspace.ws,
        issue_id=issue_id,
        branch_prefix=PREFIX,
        environ=dict(os.environ),
    )


def use_mixed_hub(workspace: Workspace) -> None:
    mixed = a_conventions_document()
    api = next(repo["conventions"] for repo in mixed["repos"] if repo["dir"] == "demo-api")
    workspace.use_conventions(project=mixed["project"]["conventions"], repos={"demo-api": api})


class TestShipSetSearch:
    def test_ships_ahead_repo_only_when_other_has_no_commits(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        api = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=2
        )
        web = make_task_worktree(
            demo_workspace, run_command, repo="demo-web", name="dem-7", commits=0
        )

        found = ship_set_of(demo_workspace)

        assert [
            (target.repo, target.worktree, target.branch, target.base, target.ahead)
            for target in found.targets
        ] == [("demo-api", api, "jdoe/dem-7-x", "trunk", 2)]
        assert [(target.repo, target.worktree, target.ahead) for target in found.skipped] == [
            ("demo-web", web, 0)
        ]
        target = found.targets[0]
        assert target.github == "acme/demo-api"
        assert target.check == "make check"
        config = load_hub_config_or_exit(demo_workspace.hub / "hub.json")
        assert target.conventions == config.conventions_for("demo-api")

    def test_ignores_longer_issue_number_when_names_share_prefix(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=2)
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-70", commits=1)
        make_task_worktree(demo_workspace, run_command, repo="demo-web", name="dem-70", commits=1)

        found = ship_set_of(demo_workspace)

        assert [(target.repo, target.branch) for target in found.targets] == [
            ("demo-api", "jdoe/dem-7-x")
        ]
        assert found.skipped == ()

    def test_uses_repo_branch_convention_when_hub_mixed(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        use_mixed_hub(demo_workspace)
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1)
        make_task_worktree(demo_workspace, run_command, repo="demo-web", name="dem-7-x", commits=1)

        found = ship_set_of(demo_workspace)

        assert [(target.repo, target.branch) for target in found.targets] == [
            ("demo-api", "feature/dem-7/x"),
            ("demo-web", "jdoe/DEM-7-x"),
        ]


def refusal_of(workspace: Workspace) -> str:
    with pytest.raises(ShipError) as raised:
        ship_set_of(workspace)
    return str(raised.value)


class TestShipSetReads:
    def test_counts_against_remote_ref_when_local_branch_shadows_it(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        worktree = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=2
        )
        demo_workspace.git(worktree, "branch", "origin/trunk", "HEAD")

        found = ship_set_of(demo_workspace)

        assert [(target.repo, target.ahead) for target in found.targets] == [("demo-api", 2)]

    def test_reads_without_tokens_or_locks_when_set_found(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1)
        calls: list[tuple[Sequence[str], dict[str, Any]]] = []

        def spy(argv: Sequence[str], **options: Any) -> ChildResult:
            calls.append((list(argv), options))
            return run_child(argv, **options)

        monkeypatch.setattr(ship_set, "run_child", spy)
        secrets = {"GH_TOKEN": "gh-x", "GITHUB_TOKEN": "github-x", "LINEAR_API_KEY": "key-x"}
        config = load_hub_config_or_exit(demo_workspace.hub / "hub.json")

        shipping_set(
            config,
            workspace=demo_workspace.ws,
            issue_id=ISSUE,
            branch_prefix=PREFIX,
            environ=dict(os.environ) | secrets,
        )

        assert [argv[1:] for argv, _ in calls] == [
            ["branch", "--show-current"],
            ["rev-list", "--count", "refs/remotes/origin/trunk..HEAD"],
        ]
        for _, options in calls:
            assert not set(secrets) & set(options["env"])
            assert options["env"]["GIT_OPTIONAL_LOCKS"] == "0"
            assert options["timeout"] == 120.0
            assert options["output_limit"] == 65536
            assert options["own_session"] is False

    def test_skips_symlinked_folder_when_real_worktree_beside_it(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        api = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1
        )
        (api.parent / "dem-7").symlink_to(demo_workspace.ws / "demo-web")

        found = ship_set_of(demo_workspace)

        assert [target.worktree for target in found.targets] == [api]

    def test_refuses_count_when_git_prints_huge_number(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1)

        def huge_count(argv: Sequence[str], **options: Any) -> ChildResult:
            if "rev-list" in argv:
                return ChildResult(returncode=0, stdout=b"9" * 5000 + b"\n", stderr=b"")
            return run_child(argv, **options)

        monkeypatch.setattr(ship_set, "run_child", huge_count)

        with pytest.raises(ShipError, match="^demo-api: git rev-list printed no count in "):
            ship_set_of(demo_workspace)


class TestShipSetRefusals:
    def test_names_both_paths_when_repo_has_two_task_worktrees(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        short = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7", commits=1
        )
        longer = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1
        )

        assert refusal_of(demo_workspace) == (
            f"demo-api: more than one task worktree for DEM-7: {short}, {longer};"
            " remove one (hub worktree --remove <name>)"
        )

    def test_counts_worktrees_when_repo_has_three(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        paths = [
            make_task_worktree(demo_workspace, run_command, repo="demo-api", name=name, commits=1)
            for name in ("dem-7", "dem-7-x", "dem-7-y")
        ]

        assert refusal_of(demo_workspace) == (
            f"demo-api: 3 task worktrees for DEM-7: {paths[0]}, {paths[1]} and 1 more;"
            " remove all but one (hub worktree --remove <name>)"
        )

    def test_names_issue_and_repos_when_no_task_worktree(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-70", commits=1)

        assert refusal_of(demo_workspace) == (
            "no task worktree for DEM-7 in demo-api, demo-web"
            " (looked for <repo>/.claude/worktrees/dem-7[-<desc>])"
        )

    def test_refuses_when_no_repo_ahead(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=0)
        make_task_worktree(demo_workspace, run_command, repo="demo-web", name="dem-7", commits=0)

        assert refusal_of(demo_workspace) == (
            "no repo has commits ahead of its base for DEM-7:"
            " demo-api (origin/trunk), demo-web (origin/trunk)"
        )

    def test_names_branches_when_worktree_on_other_branch(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        worktree = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1
        )
        demo_workspace.git(worktree, "switch", "-q", "-c", "jdoe/other")

        assert refusal_of(demo_workspace) == (
            f"demo-api: {worktree} is on jdoe/other, not jdoe/dem-7-x"
        )

    def test_names_detached_head_when_worktree_detached(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        worktree = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1
        )
        demo_workspace.git(worktree, "switch", "-q", "--detach")

        assert refusal_of(demo_workspace) == (
            f"demo-api: {worktree} is on a detached HEAD, not jdoe/dem-7-x"
        )

    def test_names_folder_when_worktree_has_no_git_entry(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1)
        folder = demo_workspace.worktree("demo-web", "dem-7")
        folder.mkdir(parents=True)

        assert refusal_of(demo_workspace) == (
            f"demo-web: {folder} is not a git worktree: it has no .git entry"
        )

    def test_names_folder_when_worktrees_unlistable(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1)
        folder = demo_workspace.ws / "demo-web" / ".claude" / "worktrees"
        folder.parent.mkdir(parents=True)
        folder.write_text("not a folder\n")

        assert refusal_of(demo_workspace) == f"demo-web: cannot list {folder}: Not a directory"

    def test_names_repo_when_base_ref_missing(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        worktree = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=1
        )
        demo_workspace.git(
            demo_workspace.ws / "demo-api", "update-ref", "-d", "refs/remotes/origin/trunk"
        )

        refusal = refusal_of(demo_workspace)

        assert refusal.startswith(f"demo-api: git rev-list failed in {worktree}: ")
        assert "origin/trunk" in refusal
        assert "\n" not in refusal


REPOS = ("demo-api", "demo-web")


class TestShipIssueFromCwd:
    def test_gives_issue_when_cwd_below_worktree(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        worktree = make_task_worktree(
            demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=0
        )
        below = worktree / "src" / "deep"
        below.mkdir(parents=True)
        link = demo_workspace.base / "link-to-ws"
        link.symlink_to(demo_workspace.ws)

        for cwd in (worktree, below, link / "demo-api" / ".claude" / "worktrees" / "dem-7-x"):
            assert (
                issue_from_cwd(cwd, workspace=demo_workspace.ws, repos=REPOS, teams=("DEM",))
                == "DEM-7"
            )
        assert issue_from_cwd(below, workspace=link, repos=REPOS, teams=("APP", "dem")) == "DEM-7"

    def test_gives_none_when_cwd_is_main_checkout(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        make_task_worktree(demo_workspace, run_command, repo="demo-api", name="dem-7-x", commits=0)
        worktrees = demo_workspace.ws / "demo-api" / ".claude" / "worktrees"
        foreign = worktrees / "xyz-3"
        foreign.mkdir()
        other_repo = demo_workspace.ws / "other" / ".claude" / "worktrees" / "dem-7"
        other_repo.mkdir(parents=True)

        for cwd in (
            demo_workspace.ws / "demo-api",
            demo_workspace.hub,
            worktrees,
            foreign,
            other_repo,
            demo_workspace.ws,
        ):
            assert (
                issue_from_cwd(cwd, workspace=demo_workspace.ws, repos=REPOS, teams=("DEM",))
                is None
            )
