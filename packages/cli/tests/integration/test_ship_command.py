"""``hub ship``: an issue's task worktrees checked, pushed, opened as PRs, linked (AC-63.3 on).

Every case runs in process, in a copy of the ``DEMO`` workspace (spec E2: team ``DEM``, repos
``demo-api`` and ``demo-web``, default branch ``trunk``, branch prefix ``jdoe/``), with
``PATH`` holding only the fakes, ``git``, ``bash`` and the interpreter (``ship_workspace``). Its
``gh`` is a scripted fake whose PRs live in a JSON state file; the tracker is a recording
in-memory one (``ship_tracker``).
"""

import json
import os
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.cli import ship_set
from agent_hub.cli.child_process import ChildResult, run_child

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

API_GITHUB = "acme/demo-api"


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
        self, ship_workspace: Workspace, make_task_worktree: Callable[..., Any], child_calls: Any
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
