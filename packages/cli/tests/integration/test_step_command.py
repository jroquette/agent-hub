"""``hub step worktree|commits|pr|report``: ``hub run``'s stages as commands (AGH-223, ADR 0032).

Each runs in process in a copy of the ``DEMO`` workspace with ``run_workspace``'s fakes (``gh``),
the real git and the local origins; stdout is one JSON object, a failure exit 1 with one
``hub step <name>: <reason>`` line on stderr. No step reads or writes the tracker.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

ISSUE = ("--issue", "DEM-1", "--repo", "demo-api")
PR_ISSUE = ("--issue", "DEM-1")
PR_URL = "https://github.com/acme/demo-api/pull/99"
SUBJECT = "feat(api): synthetic change (DEM-1)"
KEY_VARIABLE = "LINEAR_API_KEY"
GH_TOKEN_VALUE = "gh" + "o_" + "y" * 36
IDENTITY = ("-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com")


@pytest.fixture(autouse=True)
def tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    # What a caller might hold: hub step keeps the GitHub token for gh only, never the key.
    monkeypatch.setenv(KEY_VARIABLE, "lin" + "_api_" + "x" * 40)
    monkeypatch.setenv("GH_TOKEN", GH_TOKEN_VALUE)


def step(run_command: CommandRunner, workspace: Workspace, *args: str) -> Result:
    return run_command(workspace.hub, "step", *args)


def output_of(result: Result) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def worktree_of(workspace: Workspace) -> Path:
    return workspace.ws / "demo-api" / ".claude" / "worktrees" / "dem-1"


def commit(workspace: Workspace, *subjects: str) -> None:
    worktree = worktree_of(workspace)
    for subject in subjects:
        with (worktree / "synthetic_change.txt").open("a") as file:
            file.write("change\n")
        workspace.git(worktree, "add", "synthetic_change.txt")
        workspace.git(worktree, *IDENTITY, "commit", "-q", "-m", subject)


def made_worktree(run_command: CommandRunner, workspace: Workspace) -> dict[str, Any]:
    return output_of(step(run_command, workspace, "worktree", *ISSUE))


def target_of(run_command: CommandRunner, workspace: Workspace) -> tuple[str, str]:
    """``--target`` and the worktree's target, as the workflow passes it on."""
    return "--target", json.dumps(made_worktree(run_command, workspace)["target"])


class TestWorktree:
    def test_prints_path_branch_and_prompt_fields_when_worktree_made(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = run_workspace.workspace
        base = workspace.origin_head("demo-api")

        result = step(run_command, workspace, "worktree", *ISSUE)

        output = output_of(result)
        worktree = worktree_of(workspace)
        assert output["path"] == str(worktree)
        assert output["branch"] == "jdoe/dem-1"
        assert output["base"] == "origin/trunk"
        assert output["hub"] == str(workspace.hub)
        assert set(output["prompt"]) == {"guard", "gate_step", "commit_shape"}
        assert "make check" in output["prompt"]["gate_step"]
        assert output["target"]["path"] == str(worktree)
        assert output["target"]["github"] == "acme/demo-api"
        assert output["target"]["default_branch"] == "trunk"
        assert output["target"]["gate"] == "make check"
        assert set(output["target"]["conventions"]) == {
            "branch",
            "commit_title",
            "pr_title",
            "titles_configured",
            "pr_title_explicit",
        }
        assert "created" in result.stderr
        assert workspace.git(worktree, "rev-parse", "HEAD") == base

    def test_keeps_worktree_when_it_exists(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = run_workspace.workspace
        made_worktree(run_command, workspace)

        result = step(run_command, workspace, "worktree", *ISSUE)

        assert output_of(result)["path"] == str(worktree_of(workspace))
        assert "exists" in result.stderr

    def test_refuses_fetch_when_clone_config_holds_helper(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = run_workspace.workspace
        clone = workspace.ws / "demo-api"
        workspace.git(clone, "config", "credential.helper", "!echo synthetic")

        result = step(run_command, workspace, "worktree", *ISSUE)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.splitlines()[-1].startswith(
            "hub step worktree: git config holds keys a fetch would use (credential.helper)"
        )
        assert not worktree_of(workspace).exists()

    def test_refuses_usage_when_repo_unknown(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = step(
            run_command, run_workspace.workspace, "worktree", "--issue", "DEM-1", "--repo", "x"
        )

        assert result.exit_code == 2
        assert "unknown repo in --repo" in result.stderr


class TestCommits:
    def test_prints_subjects_and_summary_when_branch_has_commits(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = run_workspace.workspace
        target = target_of(run_command, workspace)
        commit(workspace, "feat(api): first (DEM-1)", SUBJECT)

        output = output_of(step(run_command, workspace, "commits", *target))

        assert output["count"] == 2
        assert output["subjects"] == [SUBJECT, "feat(api): first (DEM-1)"]
        assert SUBJECT in output["summary"]
        assert output["dirty"] is False

    def test_prints_zero_when_branch_has_no_commit(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = run_workspace.workspace
        target = target_of(run_command, workspace)

        output = output_of(step(run_command, workspace, "commits", *target))

        assert output == {"count": 0, "subjects": [], "summary": "", "dirty": False}

    def test_says_dirty_when_tracked_change_left_beside_commits(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = run_workspace.workspace
        target = target_of(run_command, workspace)
        commit(workspace, SUBJECT)
        with (worktree_of(workspace) / "synthetic_change.txt").open("a") as file:
            file.write("left behind\n")

        output = output_of(step(run_command, workspace, "commits", *target))

        assert (output["count"], output["dirty"]) == (1, True)

    def test_refuses_target_when_path_leaves_workspace(
        self, run_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        workspace = run_workspace.workspace
        target = json.loads(target_of(run_command, workspace)[1])
        target["path"] = str(tmp_path)

        result = step(run_command, workspace, "commits", "--target", json.dumps(target))

        assert result.exit_code == 2
        assert "--target" in result.stderr


class TestPr:
    def test_pushes_and_opens_pr_with_gh_token_only_when_commits_made(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = run_workspace.workspace
        target = target_of(run_command, workspace)
        commit(workspace, SUBJECT)

        result = step(run_command, workspace, "pr", *PR_ISSUE, *target, "--summary", "Adds it.")

        output = output_of(result)
        assert output == {
            "url": PR_URL,
            "found": False,
            "summary": "Adds it.",
            "title_unmatched": None,
        }
        assert (
            workspace.git(workspace.origin("demo-api"), "log", "-1", "--format=%s", "jdoe/dem-1")
            == SUBJECT
        )
        (gh,) = run_workspace.calls("gh")
        assert gh["cwd"] == str(worktree_of(workspace))
        assert gh["argv"][-1] == "DEM-1\n\nAdds it.\n\n## Verification\nGates green: `make check`."
        assert "GH_TOKEN" in gh["env"]
        assert KEY_VARIABLE not in gh["env"]

    def test_uses_commit_messages_when_summary_blank(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = run_workspace.workspace
        target = target_of(run_command, workspace)
        commit(workspace, SUBJECT)

        output = output_of(step(run_command, workspace, "pr", *PR_ISSUE, *target, "--summary", ""))

        assert SUBJECT in output["summary"]

    def test_fails_when_gh_fails(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = run_workspace.workspace
        target = target_of(run_command, workspace)
        commit(workspace, SUBJECT)
        monkeypatch.setenv("FAKE_GH_MODE", "fail")

        result = step(run_command, workspace, "pr", *PR_ISSUE, *target, "--summary", "Adds it.")

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.splitlines()[-1].startswith(
            "hub step pr: gh pr create failed: gh: synthetic failure"
        )


class TestReport:
    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (
                ("--status", "done", "--commits", "1", "--pr", PR_URL, "--summary", "Adds it."),
                {"delivery": "delivered", "stage": "", "reason": "", "question": ""},
            ),
            (
                ("--status", "done", "--commits", "0"),
                {
                    "delivery": "no_changes",
                    "stage": "IMPLEMENTING",
                    "reason": "no commit on the branch (the session reported done or gave no"
                    " verdict)",
                    "question": "",
                },
            ),
            (
                ("--status", "blocked", "--question", "Which API?", "--commits", ""),
                {
                    "delivery": "blocked",
                    "stage": "IMPLEMENTING",
                    "reason": "the implementing session stopped: Which API?",
                    "question": "Which API?",
                },
            ),
            (
                ("--status", "done", "--commits", "1", "--dirty", "true"),
                {
                    "delivery": "failed",
                    "stage": "VERIFYING",
                    "reason": "uncommitted changes in the worktree",
                    "question": "",
                },
            ),
            (
                ("--status", "done", "--commits", "2", "--pr", ""),
                {
                    "delivery": "failed",
                    "stage": "PR_OPEN",
                    "reason": "no PR was opened for the commits",
                    "question": "",
                },
            ),
        ],
    )
    def test_prints_delivery_without_tracker_when_steps_given(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        args: tuple[str, ...],
        expected: dict[str, str],
    ) -> None:
        result = step(run_command, run_workspace.workspace, "report", *args)

        output = output_of(result)
        assert {key: output[key] for key in expected} == expected
        assert output["pr"] == (PR_URL if expected["delivery"] == "delivered" else "")
        for tool in ("claude", "gh", "make"):
            assert run_workspace.calls(tool) == []

    def test_refuses_commits_when_not_a_count(
        self, run_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = step(run_command, run_workspace.workspace, "report", "--commits", "many")

        assert result.exit_code == 2
        assert "--commits" in result.stderr


class TestVerdict:
    @pytest.mark.parametrize(
        ("reply", "expected"),
        [
            (
                'Done.\n{"status": "done", "summary": "Adds it.", "tests": "make check"}',
                {"status": "done", "summary": "Adds it.", "question": ""},
            ),
            ("I made the change.", {"status": "done", "summary": "", "question": ""}),
            ("", {"status": "done", "summary": "", "question": ""}),
            (
                'Stopping.\n{"status": "blocked", "summary": "needs a plan"}',
                {"status": "blocked", "summary": "needs a plan", "question": "needs a plan"},
            ),
            (
                "BLOCKED: the issue has an open question",
                {
                    "status": "blocked",
                    "summary": "",
                    "question": "BLOCKED: the issue has an open question",
                },
            ),
        ],
    )
    def test_reads_reply_as_hub_run_does_when_verdict_asked(
        self,
        run_workspace: Workspace,
        run_command: CommandRunner,
        *,
        reply: str,
        expected: dict[str, str],
    ) -> None:
        result = step(run_command, run_workspace.workspace, "verdict", "--", reply)

        assert output_of(result) == expected


def test_lists_five_steps_when_help_asked(
    run_workspace: Workspace, run_command: CommandRunner
) -> None:
    result = step(run_command, run_workspace.workspace, "--help")

    assert result.exit_code == 0
    for name in ("worktree", "commits", "pr", "report", "verdict"):
        assert name in result.stdout
