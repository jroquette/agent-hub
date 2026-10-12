from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_hub.core.learnings.brain_change_requests import RefspecRefusedError
from agent_hub.hub_git.git_runner import GitRunner, ProcessResult
from agent_hub.hub_git.refspec_guard import push_argv

BRANCH = "demo/learning-accept-testing-x"


class SpyLauncher:
    """Records every child the runner would start; never starts one."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        keep_stdout: bool,
    ) -> ProcessResult:
        del cwd, env, timeout, keep_stdout
        self.calls.append(list(argv))
        return ProcessResult(returncode=0, stdout=b"")


def _refused_push(tmp_path: Path, branch: str, *, prefix: str = "demo/") -> SpyLauncher:
    spy = SpyLauncher()
    runner = GitRunner(environ={"PATH": "/usr/bin:/bin"}, launch=spy)
    with pytest.raises(RefspecRefusedError) as refused:
        runner.start().push(branch, cwd=tmp_path, default_branch="main", prefix=prefix)
    assert refused.value.reason
    return spy


def test_builds_push_of_one_new_branch_when_learning_branch_given() -> None:
    argv = push_argv(BRANCH, default_branch="main", prefix="demo/")

    assert argv == ["push", "--no-verify", "origin", f"refs/heads/{BRANCH}:refs/heads/{BRANCH}"]


def test_builds_branch_deletion_when_delete_asked() -> None:
    argv = push_argv(BRANCH, default_branch="main", prefix="demo/", delete=True)

    assert argv == ["push", "--no-verify", "origin", "--delete", f"refs/heads/{BRANCH}"]


def test_accepts_learning_branch_when_prefix_empty() -> None:
    argv = push_argv("learning-reject-x", default_branch="main", prefix="")

    assert argv[-1] == "refs/heads/learning-reject-x:refs/heads/learning-reject-x"


@pytest.mark.parametrize("branch", ["main", "refs/heads/main"])
def test_refuses_push_when_branch_is_default(tmp_path: Path, branch: str) -> None:
    spy = _refused_push(tmp_path, branch, prefix="")

    assert spy.calls == []


def test_refuses_push_when_default_branch_is_learning_name(tmp_path: Path) -> None:
    spy = SpyLauncher()
    runner = GitRunner(environ={"PATH": "/usr/bin:/bin"}, launch=spy)

    with pytest.raises(RefspecRefusedError):
        runner.start().push(BRANCH, cwd=tmp_path, default_branch=BRANCH, prefix="demo/")
    assert spy.calls == []


@pytest.mark.parametrize(
    "branch",
    [f"+{BRANCH}", f"{BRANCH}:main", f"HEAD:refs/heads/{BRANCH}", f"+{BRANCH}:{BRANCH}"],
)
def test_refuses_push_when_refspec_forces(tmp_path: Path, branch: str) -> None:
    spy = _refused_push(tmp_path, branch)

    assert spy.calls == []


@pytest.mark.parametrize("branch", ["--force", "-f", "--force-with-lease", "--force-if-includes"])
def test_refuses_push_when_force_flag_given(tmp_path: Path, branch: str) -> None:
    spy = _refused_push(tmp_path, branch, prefix="")

    assert spy.calls == []


@pytest.mark.parametrize(
    "branch",
    ["demo/feature-x", "other/learning-accept-x", "learning-accept-x", "demo/learning-"],
)
def test_refuses_push_when_branch_lacks_learning_prefix(tmp_path: Path, branch: str) -> None:
    spy = _refused_push(tmp_path, branch)

    assert spy.calls == []


@pytest.mark.parametrize(
    "branch",
    [
        "demo/learning-a..b",
        "demo/learning-a b",
        "demo/learning-a~1",
        "demo/learning-a.lock",
        "demo/learning-a/",
        "demo//learning-a",
        "demo/learning-a@{1}",
        "demo/learning-a\nb",
    ],
)
def test_refuses_push_when_branch_name_invalid(tmp_path: Path, branch: str) -> None:
    spy = _refused_push(tmp_path, branch)

    assert spy.calls == []


def test_refuses_deletion_when_branch_is_default() -> None:
    with pytest.raises(RefspecRefusedError):
        push_argv("main", default_branch="main", prefix="", delete=True)
