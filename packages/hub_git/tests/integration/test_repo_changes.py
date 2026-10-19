"""``GitRepoChanges`` against a real repository in ``tmp_path``: a clone of a bare ``origin``
whose branch has commits, a staged and an unstaged change and an untracked file. Synthetic
content only."""

import os
import subprocess
from pathlib import Path

import pytest

from agent_hub.core.agent_sessions.repo_changes import RepoChangesError
from agent_hub.hub_git.repo_changes import GitRepoChanges

_IDENTITY = {
    "GIT_AUTHOR_NAME": "Ana Test",
    "GIT_AUTHOR_EMAIL": "ana@example.com",
    "GIT_COMMITTER_NAME": "Ana Test",
    "GIT_COMMITTER_EMAIL": "ana@example.com",
}


def _env(home: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        **_IDENTITY,
    }


def _git(cwd: Path, env: dict[str, str], *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A clone on branch ``tip-1`` with two commits past ``origin/main`` and local changes."""
    env = _env(tmp_path)
    bare = tmp_path / "origin.git"
    _git(tmp_path, env, "init", "--bare", "--initial-branch=main", str(bare))
    work = tmp_path / "work"
    _git(tmp_path, env, "clone", str(bare), str(work))
    _git(work, env, "checkout", "-b", "main")
    (work / "app.py").write_text("a\nb\nc\n")
    (work / "old.py").write_text("x\n")
    (work / "tests.py").write_text("t1\nt2\nt3\n")
    _git(work, env, "add", ".")
    _git(work, env, "commit", "-m", "base")
    _git(work, env, "push", "origin", "main")
    _git(work, env, "remote", "set-head", "origin", "main")
    _git(work, env, "checkout", "-b", "tip-1")
    (work / "app.py").write_text("a\nB\nc\n")
    _git(work, env, "commit", "-am", "change b")
    _git(work, env, "rm", "-q", "tests.py")
    (work / "new.py").write_text("one\ntwo\n")
    _git(work, env, "add", "new.py")
    _git(work, env, "commit", "-m", "drop tests, add new")
    # Not committed: an unstaged edit, a staged one and an untracked file.
    (work / "app.py").write_text("a\nB\nc\nd\n")
    (work / "old.py").write_text("y\n")
    _git(work, env, "add", "old.py")
    (work / "draft.md").write_text("# draft\n")
    return work, env


def test_reads_every_change_against_the_fork_whoever_made_it(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    work, env = checkout

    changes = GitRepoChanges(environ=env).read(str(work), label="work")

    assert (changes.branch, changes.base) == ("tip-1", "origin/main")
    assert [commit.subject for commit in changes.commits] == ["drop tests, add new", "change b"]
    files = {Path(file.path).name: file for file in changes.files}
    assert {name: file.status for name, file in files.items()} == {
        "app.py": "modified",
        "new.py": "added",
        "old.py": "modified",
        "tests.py": "deleted",
        "draft.md": "added",
    }
    assert (files["app.py"].added, files["app.py"].removed) == (2, 1)
    assert (files["tests.py"].added, files["tests.py"].removed) == (0, 3)
    assert files["app.py"].path == str(work / "app.py")
    assert files["app.py"].uncommitted
    assert not files["new.py"].uncommitted
    assert files["draft.md"].uncommitted
    assert files["draft.md"].diff == "--- /dev/null\n+++ b/draft.md\n@@ -0,0 +1,1 @@\n+# draft"
    assert [commit.added for commit in files["app.py"].commits] == [1]
    assert files["old.py"].commits == ()


def test_the_fingerprint_changes_when_the_file_s_diff_does(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    work, env = checkout
    reader = GitRepoChanges(environ=env)
    before = {Path(f.path).name: f.fingerprint for f in reader.read(str(work), label="w").files}

    (work / "app.py").write_text("a\nB\nc\nd\ne\n")
    after = {Path(f.path).name: f.fingerprint for f in reader.read(str(work), label="w").files}

    assert before["app.py"] != after["app.py"]
    assert before["new.py"] == after["new.py"]


def test_a_folder_that_is_not_a_checkout_cannot_be_read(tmp_path: Path) -> None:
    with pytest.raises(RepoChangesError):
        GitRepoChanges(environ=_env(tmp_path)).read(str(tmp_path), label="plain")


def test_without_a_base_branch_nothing_is_compared(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _git(tmp_path, env, "init", "--initial-branch=trunk", "-q")
    (tmp_path / "a.txt").write_text("a\n")
    _git(tmp_path, env, "add", "a.txt")
    _git(tmp_path, env, "commit", "-qm", "first")

    changes = GitRepoChanges(environ=env).read(str(tmp_path), label="solo")

    assert (changes.branch, changes.base, changes.files) == ("trunk", None, ())
