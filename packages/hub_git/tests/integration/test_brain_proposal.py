"""``GitBrainChangeRequests.propose`` against a real bare ``origin``, the user's hub checkout and
a fake ``gh`` (fixtures in ``tests/conftest.py``)."""

from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.learnings.brain_change_requests import (
    BrainProposal,
    ChangeRequestConflictError,
    ChangeRequestFailedError,
    CommitAuthor,
)
from agent_hub.core.testing.builders import a_brain_proposal
from agent_hub.hub_git.brain_change_requests import (
    NOT_SIGNED_IN,
    READ_ONLY,
    GitBrainChangeRequests,
)
from agent_hub.hub_git.git_runner import GitRunner

# ``GitWorld`` and ``GitBrainOrigin`` from tests/conftest.py (a conftest is not importable).
type GitWorld = Any
type GitBrainOrigin = Any

HUB_REPO = "acme/demo-hub"
SEEDED = "brain/_inbox/testing-y.md"
SEEDED_TEXT = "---\ntype: learning\nstatus: proposed\n---\n# Testing y\n\nRun it last.\n"
AUTHOR = CommitAuthor(name="Demo Owner", email="owner@example.com")


def _proposal(world: GitWorld, **overrides: object) -> BrainProposal:
    fields: dict[str, object] = {
        "hub_path": str(world.hub),
        "hub_repo": HUB_REPO,
        "default_branch": "main",
        "author": AUTHOR,
    }
    return a_brain_proposal(**(fields | overrides))


def _temp_folders(world: GitWorld) -> list[Path]:
    temp = world.root / "temp"
    return list(temp.glob("hub-learning-*")) if temp.exists() else []


@pytest.fixture
def origin(brain_origin: GitBrainOrigin) -> GitBrainOrigin:
    brain_origin.put_on_default(SEEDED, SEEDED_TEXT)
    return brain_origin


def test_commits_only_note_on_branch_from_default_when_proposed(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    main_before = git_world.origin_git("rev-parse", "refs/heads/main").stdout.strip()
    proposal = _proposal(git_world)

    result = git_world.adapter().propose(proposal)

    branch = f"refs/heads/{proposal.branch}"
    assert result.branch == "demo/learning-propose-testing-x"
    assert result.pr_url == f"https://github.com/{HUB_REPO}/pull/1"
    count = git_world.origin_git("rev-list", "--count", f"refs/heads/main..{branch}").stdout
    assert count.strip() == "1"
    parent = git_world.origin_git("rev-parse", f"{branch}^").stdout.strip()
    assert parent == main_before
    changed = git_world.origin_git("diff", "--name-status", "refs/heads/main", branch).stdout
    assert changed == f"A\tbrain/{proposal.note}\n"
    assert origin.file_on(proposal.branch, f"brain/{proposal.note}") == proposal.text
    commit = git_world.origin_git("log", "-1", "--format=%an <%ae>%n%cn <%ce>%n%B", branch).stdout
    assert commit == (
        "Demo Owner <owner@example.com>\nDemo Owner <owner@example.com>\n"
        "docs(brain): propose learning testing-x\n\n"
    )
    assert git_world.origin_git("rev-parse", "refs/heads/main").stdout.strip() == main_before


def test_leaves_user_checkout_when_proposed(git_world: GitWorld, origin: GitBrainOrigin) -> None:
    git_world.git("pull", "--quiet", "origin", "main")
    (git_world.hub / "scratch.txt").write_text("the user's own work\n")
    before = git_world.snapshot()
    files_before = sorted(str(p.relative_to(git_world.hub)) for p in git_world.hub.rglob("*"))

    git_world.adapter().propose(_proposal(git_world))

    assert git_world.snapshot() == before
    files_after = sorted(str(p.relative_to(git_world.hub)) for p in git_world.hub.rglob("*"))
    assert files_after == files_before
    assert _temp_folders(git_world) == []


def test_passes_title_and_body_to_gh_when_proposed(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    proposal = _proposal(
        git_world,
        title="Learning proposal: Testing x — with “quotes” and $HOME",
        body="Adds brain/_inbox/2026-10-21-testing-x.md (provenance agent).\n\n> `x` $(y)",
    )

    git_world.adapter().propose(proposal)

    [create] = [call for call in git_world.gh_calls() if call[:2] == ["pr", "create"]]
    assert f"--title={proposal.title}" in create
    assert "--base=main" in create
    assert f"--head={proposal.branch}" in create
    [pull] = origin.pull_requests()
    assert (pull.title, pull.body) == (proposal.title, proposal.body)


def test_leaves_origin_without_branch_and_deletes_nothing_when_push_rejected(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    git_world.reject_pushes()
    proposal = _proposal(git_world)

    with pytest.raises(ChangeRequestFailedError) as failed:
        git_world.adapter(git_world.logging_runner()).propose(proposal)

    assert failed.value.step == "push"
    assert origin.branch_names() == {"main"}
    assert origin.pull_requests() == ()
    assert [call for call in git_world.git_calls() if " push " in f" {call} "] == [
        "-c core.askPass= push --no-verify origin "
        f"refs/heads/{proposal.branch}:refs/heads/{proposal.branch}"
    ]
    assert _temp_folders(git_world) == []


def test_keeps_branch_another_session_pushed_when_push_rejected(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    proposal = _proposal(git_world)
    # Another session's commit, kept on origin under another name until the race.
    (git_world.seed / "other.txt").write_text("another session's note\n")
    git_world.git("checkout", "--quiet", "-b", "other", cwd=git_world.seed)
    git_world.git("add", "other.txt", cwd=git_world.seed)
    git_world.git("commit", "--quiet", "-m", "docs: another session", cwd=git_world.seed)
    git_world.git("push", "--quiet", "origin", "other", cwd=git_world.seed)
    theirs = git_world.origin_git("rev-parse", "refs/heads/other").stdout.strip()
    # It takes the branch after this call checked it is free and before its push: the push is
    # then not a fast-forward and origin rejects it.
    race = f'git --git-dir="{git_world.bare}" update-ref refs/heads/{proposal.branch} {theirs}; '

    with pytest.raises(ChangeRequestFailedError) as failed:
        git_world.adapter(git_world.logging_runner(before_push=race)).propose(proposal)

    assert failed.value.step == "push"
    head = git_world.origin_git("rev-parse", f"refs/heads/{proposal.branch}").stdout.strip()
    assert head == theirs
    assert [call for call in git_world.git_calls() if "--delete" in call] == []
    assert origin.pull_requests() == ()
    assert _temp_folders(git_world) == []


def test_removes_branch_and_clone_when_pull_request_fails(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    git_world.switch("fail")
    proposal = _proposal(git_world)

    with pytest.raises(ChangeRequestFailedError) as failed:
        git_world.adapter().propose(proposal)

    assert failed.value.step == "pr"
    assert origin.branch_names() == {"main"}
    assert origin.pull_requests() == ()
    assert _temp_folders(git_world) == []


def test_refuses_proposal_when_origin_is_other_repo(
    git_world: GitWorld, origin: GitBrainOrigin
) -> None:
    with pytest.raises(ChangeRequestConflictError) as conflict:
        git_world.adapter().propose(_proposal(git_world, hub_repo="acme/other"))

    assert conflict.value.reason == "Hub remote is not acme/other"
    assert origin.branch_names() == {"main"}
    assert _temp_folders(git_world) == []


@pytest.mark.parametrize(
    "case",
    [({"AGENT_HUB_IN_CONTAINER": "1"}, None, READ_ONLY), ({}, "logged-out", NOT_SIGNED_IN)],
)
def test_refuses_proposal_when_hub_unavailable(
    git_world: GitWorld, origin: GitBrainOrigin, case: tuple[dict[str, str], str | None, str]
) -> None:
    environ, switch, reason = case
    if switch is not None:
        git_world.switch(switch)
    temp = git_world.root / "temp"
    temp.mkdir(exist_ok=True)
    adapter = GitBrainChangeRequests(GitRunner(environ=git_world.environ | environ), temp_root=temp)

    with pytest.raises(ChangeRequestConflictError) as conflict:
        adapter.propose(_proposal(git_world))

    assert conflict.value.reason == reason
    assert origin.branch_names() == {"main"}
    assert list(temp.iterdir()) == []
    assert [call for call in git_world.gh_calls() if call[:1] == ["pr"]] == []
