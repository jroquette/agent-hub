"""The ADR 0024 steps of ``GitBrainChangeRequests`` against a real bare ``origin``, the user's
hub checkout and a fake ``gh`` (fixtures in ``tests/conftest.py``)."""

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.learnings.brain_change_requests import (
    BrainChange,
    ChangeRequestConflictError,
    ChangeRequestFailedError,
    CommitAuthor,
    RefspecRefusedError,
)
from agent_hub.core.testing.builders import a_brain_change
from agent_hub.hub_git.brain_change_requests import (
    NO_GH,
    NO_GIT,
    NOT_A_CHECKOUT,
    NOT_GITHUB,
    NOT_SIGNED_IN,
    READ_ONLY,
    GitBrainChangeRequests,
)
from agent_hub.hub_git.git_runner import GitRunner

# ``GitWorld`` and ``GitBrainOrigin`` from tests/conftest.py (a conftest is not importable).
type GitWorld = Any
type GitBrainOrigin = Any

HUB_REPO = "acme/demo-hub"
DEFAULT_BRANCH = "main"

NOTE = "brain/_inbox/testing-x.md"
NOTE_TEXT = "---\ntype: learning\nstatus: proposed\n---\n# Testing x\n\nRun it first.\n"
AUTHOR = CommitAuthor(name="Demo Owner", email="owner@example.com")


def _change(world: GitWorld, **overrides: object) -> BrainChange:
    fields: dict[str, object] = {
        "hub_path": str(world.hub),
        "hub_repo": HUB_REPO,
        "default_branch": DEFAULT_BRANCH,
        "author": AUTHOR,
    }
    return a_brain_change(**(fields | overrides))


def _rejection(world: GitWorld) -> BrainChange:
    return _change(
        world,
        action="reject",
        destination="_inbox/_archive/testing-x.md",
        frontmatter={"status": "rejected", "rejected_reason": "Duplicate of y"},
        branch="demo/learning-reject-testing-x",
        title="Reject learning: Testing x",
        body="Archives brain/_inbox/testing-x.md.\n\nReason: Duplicate of y",
        commit_message="docs(brain): reject learning testing-x",
    )


@pytest.fixture
def origin(brain_origin: GitBrainOrigin) -> GitBrainOrigin:
    brain_origin.put_on_default(NOTE, NOTE_TEXT)
    return brain_origin


def test_pushes_branch_with_moved_note_when_accepted(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    main_before = git_world.origin_git("rev-parse", "refs/heads/main").stdout
    change = _change(git_world)

    result = git_world.adapter().accept(change)

    assert result.branch == change.branch
    assert result.pr_url == f"https://github.com/{HUB_REPO}/pull/1"
    log = git_world.origin_git(
        "rev-list", "--count", f"refs/heads/main..refs/heads/{change.branch}"
    )
    assert log.stdout.strip() == "1"
    commit = git_world.origin_git(
        "log", "-1", "--format=%an <%ae>%n%cn <%ce>%n%B", f"refs/heads/{change.branch}"
    ).stdout
    assert commit == (
        "Demo Owner <owner@example.com>\nDemo Owner <owner@example.com>\n"
        "docs(brain): accept learning testing-x\n\n"
    )
    moved = origin.file_on(change.branch, "brain/learnings/testing-x.md")
    assert moved is not None
    assert split_frontmatter(moved).fields["last_verified"] == "2026-10-12"
    assert moved.endswith("# Testing x\n\nRun it first.\n")
    assert git_world.origin_git("rev-parse", "refs/heads/main").stdout == main_before
    pull = origin.pull_requests()[0]
    assert (pull.head, pull.base, pull.title) == (change.branch, "main", change.title)


def test_archives_note_with_reason_when_rejected(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    change = _rejection(git_world)

    result = git_world.adapter().reject(change)

    archived = origin.file_on(change.branch, "brain/_inbox/_archive/testing-x.md")
    assert archived is not None
    fields = split_frontmatter(archived).fields
    assert fields["status"] == "rejected"
    assert fields["rejected_reason"] == "Duplicate of y"
    assert origin.file_on(change.branch, NOTE) is None
    assert origin.pull_requests()[0].body == change.body
    assert result.pr_url.endswith("/pull/1")


def test_leaves_user_checkout_when_action_runs(git_world: GitWorld, origin: GitBrainOrigin) -> None:
    git_world.git("pull", "--quiet", "origin", "main")
    (git_world.hub / "scratch.txt").write_text("the user's own work\n")
    before = git_world.snapshot()
    files_before = sorted(str(p.relative_to(git_world.hub)) for p in git_world.hub.rglob("*"))

    git_world.adapter().accept(_change(git_world))
    git_world.adapter().reject(
        _rejection(git_world).model_copy(update={"branch": "demo/learning-reject-testing-x"})
    )

    assert git_world.snapshot() == before
    files_after = sorted(str(p.relative_to(git_world.hub)) for p in git_world.hub.rglob("*"))
    assert files_after == files_before
    assert not list((git_world.root / "temp").iterdir())


def test_deletes_pushed_branch_when_gh_fails(git_world: GitWorld, origin: GitBrainOrigin) -> None:
    git_world.switch("fail")
    change = _change(git_world)

    with pytest.raises(ChangeRequestFailedError) as failed:
        git_world.adapter().accept(change)

    assert failed.value.step == "pr"
    assert change.branch not in origin.branch_names()
    assert origin.pull_requests() == ()
    assert git_world.gh_calls()[-1][:2] == ["pr", "create"]
    assert not list((git_world.root / "temp").iterdir())


def test_deletes_pushed_branch_when_gh_output_unexpected(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    git_world.switch("garbage")
    change = _change(git_world)

    with pytest.raises(ChangeRequestFailedError) as failed:
        git_world.adapter().accept(change)

    assert failed.value.step == "pr"
    assert change.branch not in origin.branch_names()


def test_succeeds_when_retried_after_failure(git_world: GitWorld, origin: GitBrainOrigin) -> None:
    change = _change(git_world)
    git_world.switch("fail")
    with pytest.raises(ChangeRequestFailedError):
        git_world.adapter().accept(change)
    git_world.switch("fail", on=False)

    result = git_world.adapter().accept(change)

    assert result.branch == change.branch
    assert len(origin.pull_requests()) == 1


def test_refuses_when_note_absent_from_default_branch(
    git_world: GitWorld, brain_origin: GitBrainOrigin
) -> None:
    probe = brain_origin
    probe.put_on_default("brain/_inbox/other.md", NOTE_TEXT)

    with pytest.raises(ChangeRequestConflictError) as conflict:
        git_world.adapter().accept(_change(git_world))

    assert conflict.value.reason == "Note not on origin/main: brain/_inbox/testing-x.md"
    assert probe.branch_names() == {"main"}
    assert git_world.gh_calls() == [["auth", "token", "--hostname", "github.com"]]


def test_refuses_when_note_only_in_user_checkout(git_world: GitWorld) -> None:
    inbox = git_world.hub / "brain" / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "testing-x.md").write_text(NOTE_TEXT)
    git_world.git("add", "brain")
    git_world.git("commit", "--quiet", "-m", "docs: local only")

    with pytest.raises(ChangeRequestConflictError, match="Note not on origin/main"):
        git_world.adapter().accept(_change(git_world))


def test_refuses_conflicts_when_note_is_a_link(git_world: GitWorld) -> None:
    inbox = git_world.seed / "brain" / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "testing-x.md").symlink_to("../../README.md")
    git_world.git("add", "brain", cwd=git_world.seed)
    git_world.git("commit", "--quiet", "-m", "docs: a link", cwd=git_world.seed)
    git_world.git("push", "--quiet", "origin", "main", cwd=git_world.seed)

    with pytest.raises(ChangeRequestConflictError, match="not a regular file"):
        git_world.adapter().accept(_change(git_world))


def test_refuses_conflicts_when_note_too_large(
    git_world: GitWorld, brain_origin: GitBrainOrigin
) -> None:
    brain_origin.put_on_default(NOTE, "x" * 262_145)

    with pytest.raises(ChangeRequestConflictError, match="too large"):
        git_world.adapter().accept(_change(git_world))


def test_refuses_conflicts_when_frontmatter_unclosed(
    git_world: GitWorld, brain_origin: GitBrainOrigin
) -> None:
    brain_origin.put_on_default(NOTE, "---\ntype: learning\n# no end\n")

    with pytest.raises(ChangeRequestConflictError, match="frontmatter"):
        git_world.adapter().accept(_change(git_world))


def test_refuses_conflicts_when_hub_repo_differs(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    with pytest.raises(ChangeRequestConflictError, match="other/hub"):
        git_world.adapter().accept(_change(git_world, hub_repo="other/hub"))
    assert origin.branch_names() == {"main"}


def test_refuses_conflicts_when_note_outside_inbox(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    change = _change(git_world, note="learnings/other.md", destination="learnings/x/other.md")

    with pytest.raises(ChangeRequestConflictError, match="_inbox"):
        git_world.adapter().accept(change)
    assert origin.branch_names() == {"main"}


def test_refuses_push_when_branch_not_learning_name(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    change = _change(git_world, branch="demo/feature-x")

    with pytest.raises(RefspecRefusedError):
        git_world.adapter().accept(change)
    assert origin.branch_names() == {"main"}


def test_refuses_push_when_branch_names_another_action(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    change = _change(git_world, branch="demo/learning-reject-testing-x")

    with pytest.raises(RefspecRefusedError):
        git_world.adapter().accept(change)
    assert origin.branch_names() == {"main"}


def test_reports_available_when_hub_ready(git_world: GitWorld) -> None:
    assert git_world.adapter().availability(str(git_world.hub)) is None


def test_reports_read_only_when_in_container(git_world: GitWorld) -> None:
    runner = GitRunner(environ=git_world.environ | {"AGENT_HUB_IN_CONTAINER": "1"})

    reason = GitBrainChangeRequests(runner).availability(str(git_world.hub))

    assert reason == READ_ONLY


def test_reports_read_only_when_hub_not_writable(git_world: GitWorld) -> None:
    mode = git_world.hub.stat().st_mode
    git_world.hub.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        if os.access(git_world.hub, os.W_OK):
            pytest.skip("running as a user that writes anywhere")
        reason = git_world.adapter().availability(str(git_world.hub))
    finally:
        git_world.hub.chmod(mode)

    assert reason == READ_ONLY


def test_reports_read_only_when_hub_missing(git_world: GitWorld) -> None:
    assert git_world.adapter().availability(str(git_world.root / "absent")) == READ_ONLY


def test_reports_no_git_when_git_missing(git_world: GitWorld) -> None:
    runner = GitRunner(environ=git_world.environ, git="no-such-git")

    assert GitBrainChangeRequests(runner).availability(str(git_world.hub)) == NO_GIT


def test_reports_no_gh_when_gh_missing(git_world: GitWorld) -> None:
    runner = GitRunner(environ=git_world.environ, gh="no-such-gh")

    assert GitBrainChangeRequests(runner).availability(str(git_world.hub)) == NO_GH


def test_reports_not_signed_in_when_gh_logged_out(git_world: GitWorld) -> None:
    git_world.switch("logged-out")

    assert git_world.adapter().availability(str(git_world.hub)) == NOT_SIGNED_IN


def test_reports_not_github_when_origin_elsewhere(git_world: GitWorld) -> None:
    git_world.git("remote", "set-url", "origin", "https://gitlab.com/acme/demo-hub.git")

    assert git_world.adapter().availability(str(git_world.hub)) == NOT_GITHUB


def test_reports_not_github_when_no_origin(git_world: GitWorld) -> None:
    git_world.git("remote", "remove", "origin")

    assert git_world.adapter().availability(str(git_world.hub)) == NOT_GITHUB


def test_reports_not_checkout_when_hub_not_git(git_world: GitWorld, tmp_path: Path) -> None:
    plain = tmp_path / "plain-hub"
    plain.mkdir()

    assert git_world.adapter().availability(str(plain)) == NOT_A_CHECKOUT


def test_reports_not_checkout_when_hub_is_subfolder(git_world: GitWorld) -> None:
    inner = git_world.hub / "brain"
    inner.mkdir()

    assert git_world.adapter().availability(str(inner)) == NOT_A_CHECKOUT


def test_refuses_conflicts_when_unavailable(git_world: GitWorld, origin: GitBrainOrigin) -> None:
    git_world.switch("logged-out")

    with pytest.raises(ChangeRequestConflictError) as conflict:
        git_world.adapter().accept(_change(git_world))

    assert conflict.value.reason == NOT_SIGNED_IN
    assert origin.branch_names() == {"main"}


def test_refuses_conflicts_when_note_not_utf8(git_world: GitWorld) -> None:
    inbox = git_world.seed / "brain" / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "testing-x.md").write_bytes(b"# Testing \xff\n")
    git_world.git("add", "brain", cwd=git_world.seed)
    git_world.git("commit", "--quiet", "-m", "docs: latin-1", cwd=git_world.seed)
    git_world.git("push", "--quiet", "origin", "main", cwd=git_world.seed)

    with pytest.raises(ChangeRequestConflictError, match="UTF-8"):
        git_world.adapter().accept(_change(git_world))
