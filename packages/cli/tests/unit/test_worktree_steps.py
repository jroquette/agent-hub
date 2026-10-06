from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import WorktreeError
from agent_hub.cli.worktree_steps import WORKTREES_FOLDER, check_branches, worktree_task
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

NAME = "dem-1-x"
BRANCH = "jdoe/dem-1-x"
ACCEPTED = ChildResult(returncode=0, stdout=b"", stderr=b"")


class ScriptedRunner:
    """A git that answers one command (the first argument after ``git``) with ``answer`` and
    accepts every other call, recording each one's argv."""

    def __init__(self, command: str, answer: ChildResult) -> None:
        self.command = command
        self.answer = answer
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str,
        env: Mapping[str, str],
        timeout: float | None,
        own_session: bool | None = None,
    ) -> ChildResult:
        del cwd, env, timeout, own_session
        self.calls.append(list(argv))
        return self.answer if argv[1] == self.command else ACCEPTED


def check(workspace: Path, runner: ScriptedRunner) -> None:
    """``check_branches`` on task ``dem-1-x`` of the one-repo demo hub at ``workspace/hub``."""
    task = worktree_task(
        HubConfig.model_validate(a_hub_document()),
        name=NAME,
        branch_prefix="jdoe/",
        only=None,
        hub=workspace / "hub",
        git="git",
        env={},
        git_timeout=None,
        runner=runner,
    )
    check_branches(task)


def cloned(workspace: Path) -> Path:
    """``demo-api`` cloned in ``workspace`` (a ``.git`` folder is all ``check_branches`` reads)."""
    checkout = workspace / "demo-api"
    (checkout / ".git").mkdir(parents=True)
    return checkout


def task_worktree(workspace: Path) -> Path:
    """The task's worktree of ``demo-api``, with the ``.git`` file git writes in one."""
    worktree = cloned(workspace) / WORKTREES_FOLDER / NAME
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: elsewhere\n")
    return worktree


def test_names_stderr_line_when_branch_of_worktree_unreadable(tmp_path: Path) -> None:
    worktree = task_worktree(tmp_path)
    failed = ChildResult(returncode=128, stdout=b"", stderr=b"\nfatal: synthetic failure\nmore\n")

    with pytest.raises(WorktreeError) as raised:
        check(tmp_path, ScriptedRunner("branch", failed))

    assert str(raised.value) == (
        f"demo-api: could not read the branch of {worktree}: fatal: synthetic failure"
    )


def test_names_stderr_line_when_branches_cannot_be_listed(tmp_path: Path) -> None:
    _ = cloned(tmp_path)
    failed = ChildResult(returncode=128, stdout=b"", stderr=b"fatal: synthetic failure\n")

    with pytest.raises(WorktreeError) as raised:
        check(tmp_path, ScriptedRunner("for-each-ref", failed))

    assert str(raised.value) == "demo-api: could not list the branches: fatal: synthetic failure"


def test_names_detached_head_when_worktree_on_no_branch(tmp_path: Path) -> None:
    worktree = task_worktree(tmp_path)
    detached = ChildResult(returncode=0, stdout=b"\n", stderr=b"")

    with pytest.raises(WorktreeError) as raised:
        check(tmp_path, ScriptedRunner("branch", detached))

    assert str(raised.value) == f"demo-api: {worktree} is on a detached HEAD, not {BRANCH}"


def test_accepts_worktree_when_on_task_branch(tmp_path: Path) -> None:
    _ = task_worktree(tmp_path)
    runner = ScriptedRunner(
        "branch", ChildResult(returncode=0, stdout=b"jdoe/dem-1-x\n", stderr=b"")
    )

    check(tmp_path, runner)

    assert runner.calls[1:] == [["git", "branch", "--show-current"]]


def test_refuses_folder_before_branch_call_when_task_folder_not_worktree(tmp_path: Path) -> None:
    folder = cloned(tmp_path) / WORKTREES_FOLDER / NAME
    folder.mkdir(parents=True)
    runner = ScriptedRunner("branch", ChildResult(returncode=0, stdout=b"trunk\n", stderr=b""))

    with pytest.raises(WorktreeError) as raised:
        check(tmp_path, runner)

    assert str(raised.value) == f"demo-api: {folder} is not a worktree; remove it"
    assert runner.calls == [["git", "check-ref-format", "--branch", BRANCH]]
