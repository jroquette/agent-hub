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


def test_reads_every_change_against_the_fork_when_anyone_made_it(
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


def _stacked(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A clone whose ``batatinha`` (one commit past ``origin/main``) is pushed, then the work
    tree's own clone of it."""
    env = _env(tmp_path)
    bare = tmp_path / "origin.git"
    _git(tmp_path, env, "init", "--bare", "--initial-branch=main", str(bare))
    work = tmp_path / "work"
    _git(tmp_path, env, "clone", str(bare), str(work))
    _git(work, env, "checkout", "-b", "main")
    (work / "app.py").write_text("a\n")
    _git(work, env, "add", ".")
    _git(work, env, "commit", "-m", "base")
    _git(work, env, "push", "origin", "main")
    _git(work, env, "remote", "set-head", "origin", "main")
    _git(work, env, "checkout", "-b", "batatinha")
    (work / "batatinha.py").write_text("b\n")
    _git(work, env, "add", ".")
    _git(work, env, "commit", "-m", "batatinha")
    _git(work, env, "push", "-u", "origin", "batatinha")
    _git(work, env, "checkout", "main")
    return work, env


@pytest.mark.parametrize("start", ["batatinha", "origin/batatinha"])
def test_compares_with_that_branch_when_a_worktree_started_from_a_branch(
    tmp_path: Path, start: str
) -> None:
    work, env = _stacked(tmp_path)
    tree = work / ".claude" / "worktrees" / "tip-2"
    _git(work, env, "worktree", "add", "-q", "-b", "tip-2", str(tree), start)
    (tree / "tip2.py").write_text("t\n")
    _git(tree, env, "add", ".")
    _git(tree, env, "commit", "-m", "tip 2")

    changes = GitRepoChanges(environ=env).read(str(tree), label="app/tip-2")

    assert changes.base == start
    assert [os.path.basename(file.path) for file in changes.files] == ["tip2.py"]


def test_compares_with_where_it_started_when_a_branch_is_pushed_with_its_upstream(
    tmp_path: Path,
) -> None:
    work, env = _stacked(tmp_path)
    _git(work, env, "checkout", "-q", "-b", "roquettejh/agh-1", "batatinha")
    (work / "agh.py").write_text("x\n")
    _git(work, env, "add", ".")
    _git(work, env, "commit", "-m", "agh")
    _git(work, env, "push", "-q", "-u", "origin", "roquettejh/agh-1")
    _git(work, env, "reflog", "expire", "--expire=all", "--all")

    changes = GitRepoChanges(environ=env).read(str(work), label="app")

    # No reflog left and an upstream that is its own pushed copy: the remote's default.
    assert changes.base == "origin/main"


def test_reads_recorded_commits_when_the_worktree_was_removed(tmp_path: Path) -> None:
    work, env = _stacked(tmp_path)
    tree = work / ".claude" / "worktrees" / "tip-3"
    _git(work, env, "worktree", "add", "-q", "-b", "tip-3", str(tree), "origin/main")
    (tree / "tip3.py").write_text("t\n")
    _git(tree, env, "add", ".")
    _git(tree, env, "commit", "-m", "tip 3")
    reader = GitRepoChanges(environ=env)
    live = reader.read(str(tree), label="app/tip-3")
    _git(work, env, "worktree", "remove", "--force", str(tree))
    _git(work, env, "branch", "-D", "tip-3")
    assert live.base_sha is not None
    assert live.head_sha is not None

    recorded = reader.read_recorded(
        str(work),
        label="app/tip-3",
        root=str(tree),
        branch="tip-3",
        base=live.base,
        base_sha=live.base_sha,
        head_sha=live.head_sha,
    )

    assert recorded.source == "recorded"
    assert [file.path for file in recorded.files] == [str(tree / "tip3.py")]
    assert [commit.subject for commit in recorded.commits] == ["tip 3"]
    assert recorded.head_sha == live.head_sha


def test_cannot_read_when_recorded_commits_are_no_longer_here(tmp_path: Path) -> None:
    work, env = _stacked(tmp_path)

    with pytest.raises(RepoChangesError):
        GitRepoChanges(environ=env).read_recorded(
            str(work),
            label="app/gone",
            root=str(work / "gone"),
            branch="gone",
            base="origin/main",
            base_sha="1" * 40,
            head_sha="2" * 40,
        )


def test_cannot_read_when_the_folder_is_not_a_checkout(tmp_path: Path) -> None:
    with pytest.raises(RepoChangesError):
        GitRepoChanges(environ=_env(tmp_path)).read(str(tmp_path), label="plain")


def test_compares_nothing_when_there_is_no_base_branch(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _git(tmp_path, env, "init", "--initial-branch=trunk", "-q")
    (tmp_path / "a.txt").write_text("a\n")
    _git(tmp_path, env, "add", "a.txt")
    _git(tmp_path, env, "commit", "-qm", "first")

    changes = GitRepoChanges(environ=env).read(str(tmp_path), label="solo")

    assert (changes.branch, changes.base, changes.files) == ("trunk", None, ())


def test_reads_one_file_s_diff_when_one_commit_is_asked(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    work, env = checkout
    reader = GitRepoChanges(environ=env)
    app = next(f for f in reader.read(str(work), label="w").files if f.path.endswith("app.py"))
    [commit] = app.commits

    diff = reader.commit_diff(str(work), sha=commit.sha[:7], paths=["app.py"])

    assert diff.sha == commit.sha
    assert diff.diff == "--- a/app.py\n+++ b/app.py\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c"


def test_reads_an_empty_diff_when_the_commit_did_not_touch_the_file(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    work, env = checkout
    reader = GitRepoChanges(environ=env)
    first = reader.read(str(work), label="w").commits[-1]

    assert reader.commit_diff(str(work), sha=first.sha, paths=["new.py"]).diff == ""


def test_cannot_read_when_the_commit_is_unknown(checkout: tuple[Path, dict[str, str]]) -> None:
    work, env = checkout

    with pytest.raises(RepoChangesError):
        GitRepoChanges(environ=env).commit_diff(str(work), sha="0" * 40, paths=["app.py"])


def _rev(cwd: Path, env: dict[str, str], ref: str) -> str:
    found = subprocess.run(  # noqa: S603
        ["git", "rev-parse", ref],  # noqa: S607
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return found.stdout.strip()


def test_reads_the_pushed_branch_when_the_recorded_head_is_no_longer_here(
    tmp_path: Path,
) -> None:
    work, env = _stacked(tmp_path)
    gone = work / ".claude" / "worktrees" / "batatinha"

    recorded = GitRepoChanges(environ=env).read_recorded(
        str(work),
        label="app/batatinha",
        root=str(gone),
        branch="batatinha",
        base="origin/main",
        base_sha=_rev(work, env, "origin/main"),
        head_sha="2" * 40,
    )

    assert recorded.head_sha == _rev(work, env, "origin/batatinha")
    assert [commit.subject for commit in recorded.commits] == ["batatinha"]
    assert [file.path for file in recorded.files] == [str(gone / "batatinha.py")]


@pytest.mark.parametrize(("base", "head"), [("--all", None), (None, "--all")])
def test_cannot_read_when_a_recorded_commit_reads_as_an_option(
    tmp_path: Path, base: str | None, head: str | None
) -> None:
    work, env = _stacked(tmp_path)
    main = _rev(work, env, "origin/main")

    with pytest.raises(RepoChangesError):
        GitRepoChanges(environ=env).read_recorded(
            str(work),
            label="app/x",
            root=str(work / "x"),
            branch=None,
            base="origin/main",
            base_sha=base or main,
            head_sha=head or main,
        )


@pytest.mark.parametrize("sha", ["--all", "--output=x"])
def test_cannot_read_a_commit_when_its_sha_reads_as_an_option(
    checkout: tuple[Path, dict[str, str]], sha: str
) -> None:
    work, env = checkout

    with pytest.raises(RepoChangesError):
        GitRepoChanges(environ=env).commit_diff(str(work), sha=sha, paths=["app.py"])
