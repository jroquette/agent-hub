"""The ``BrainChangeRequests`` contract suite (ADR 0024): the in-memory fake and the ``hub_git``
adapter honour it.

An implementation's ``tests/contract/`` provides two fixtures: ``brain_origin``, a
``BrainOrigin`` probe of the hub's ``origin`` (empty default branch, no pull request), and
``brain_change_requests``, the adapter acting on it; then it declares
``class Test<Implementation>(BrainChangeRequestsContract)``. Checks raise ``AssertionError`` by
hand: core ships this suite without depending on pytest. Paths given to the probe are relative
to the hub root (``brain/_inbox/x.md``).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from agent_hub.core.brain.brain_path import BRAIN_FOLDER
from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.learnings.brain_change_requests import (
    BrainChange,
    BrainChangeRequests,
    ChangeRequestConflictError,
    ChangeRequestResult,
)
from agent_hub.core.testing.builders import a_brain_change

NOTE = "_inbox/testing-x.md"
NOTE_TEXT = "---\ntype: learning\nstatus: proposed\n---\n# Testing x\n\nRun it first.\n"
ACCEPTED = "learnings/testing-x.md"
ARCHIVED = "_inbox/_archive/testing-x.md"


@dataclass(frozen=True, kw_only=True, slots=True)
class OriginCommit:
    """The head commit of a branch: author and message."""

    author_name: str
    author_email: str
    message: str


@dataclass(frozen=True, kw_only=True, slots=True)
class OpenedPullRequest:
    """A pull request the adapter opened."""

    url: str
    head: str
    base: str
    title: str
    body: str


class BrainOrigin(Protocol):
    """What the suite reads and seeds of the hub's ``origin``."""

    @property
    def hub_path(self) -> str:
        """The hub checkout the changes name."""
        ...

    @property
    def hub_repo(self) -> str:
        """The hub's GitHub ``owner/name``."""
        ...

    @property
    def default_branch(self) -> str:
        """The origin's default branch."""
        ...

    def put_on_default(self, path: str, text: str) -> None:
        """Commit ``text`` at the hub-relative ``path`` on the default branch."""
        ...

    def file_on(self, branch: str, path: str) -> str | None:
        """The text at ``path`` on ``branch``; None when absent (or no such branch)."""
        ...

    def branch_names(self) -> frozenset[str]:
        """The origin's branches."""
        ...

    def head_commit(self, branch: str) -> OriginCommit | None:
        """The head commit of ``branch``; None when there is no such branch."""
        ...

    def pull_requests(self) -> tuple[OpenedPullRequest, ...]:
        """The pull requests opened so far, in order."""
        ...


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


def _in_brain(path: str) -> str:
    return f"{BRAIN_FOLDER}/{path}"


def _change(origin: BrainOrigin, **overrides: object) -> BrainChange:
    return a_brain_change(
        hub_path=origin.hub_path,
        hub_repo=origin.hub_repo,
        default_branch=origin.default_branch,
        **overrides,
    )


def _rejection(origin: BrainOrigin) -> BrainChange:
    return _change(
        origin,
        action="reject",
        destination=ARCHIVED,
        frontmatter={"status": "rejected", "rejected_reason": "Duplicate of x"},
        branch="demo/learning-reject-testing-x",
        title="Reject learning: Testing x",
    )


def _refused(action: Callable[[], ChangeRequestResult], origin: BrainOrigin) -> None:
    branches = origin.branch_names()
    pulls = origin.pull_requests()
    try:
        action()
    except ChangeRequestConflictError as error:
        _check(bool(error.reason), "a conflict names its reason")
        _check(origin.branch_names() == branches, "a refused change pushes no branch")
        _check(origin.pull_requests() == pulls, "a refused change opens no pull request")
        return
    raise AssertionError("expected ChangeRequestConflictError")


class BrainChangeRequestsContract:
    """Accept and reject open one PR from one new branch and never touch the default branch; a
    retry adopts the open PR of a branch already pushed."""

    def test_reports_available_when_hub_ready(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        _check(brain_change_requests.availability(brain_origin.hub_path) is None, "available")

    def test_moves_note_on_new_branch_when_accepted(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        change = _change(brain_origin)

        result = brain_change_requests.accept(change)

        moved = brain_origin.file_on(change.branch, _in_brain(ACCEPTED))
        _check(result.branch == change.branch, "the result names the pushed branch")
        _check(moved is not None, "the note is at its destination on the branch")
        fields = split_frontmatter(moved or "").fields
        _check(fields.get("status") == "accepted", "the frontmatter is set")
        _check(fields.get("type") == "learning", "other frontmatter fields are kept")
        _check(brain_origin.file_on(change.branch, _in_brain(NOTE)) is None, "inbox note moved")
        commit = brain_origin.head_commit(change.branch)
        _check(commit is not None, "the branch has a commit")
        _check(
            commit is not None
            and (commit.author_name, commit.author_email)
            == (change.author.name, change.author.email),
            "the commit is by the hub's author",
        )
        _check(
            commit is not None and commit.message.strip() == change.commit_message,
            "the commit message is the change's, with no trailer",
        )

    def test_writes_edited_body_with_frontmatter_when_accepted_with_edit(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        change = _change(brain_origin, note_body="# Testing x\n\nRun it first, then check.\n")

        brain_change_requests.accept(change)

        moved = split_frontmatter(brain_origin.file_on(change.branch, _in_brain(ACCEPTED)) or "")
        _check(moved.body == "# Testing x\n\nRun it first, then check.\n", "the body is the edit")
        _check(moved.fields.get("type") == "learning", "the frontmatter is kept")
        _check(moved.fields.get("status") == "accepted", "the frontmatter is set")

    def test_leaves_default_branch_when_accepted(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        before = brain_origin.head_commit(brain_origin.default_branch)

        brain_change_requests.accept(_change(brain_origin))

        default = brain_origin.default_branch
        _check(brain_origin.head_commit(default) == before, "the default branch did not move")
        _check(brain_origin.file_on(default, _in_brain(NOTE)) == NOTE_TEXT, "inbox note kept")
        _check(brain_origin.file_on(default, _in_brain(ACCEPTED)) is None, "nothing added")

    def test_opens_one_pull_request_when_accepted(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        change = _change(brain_origin)

        result = brain_change_requests.accept(change)

        pulls = brain_origin.pull_requests()
        _check(len(pulls) == 1, "one pull request")
        pull = pulls[0]
        _check(pull.url == result.pr_url, "the result names the pull request")
        _check(
            result.pr_url.startswith(f"https://github.com/{brain_origin.hub_repo}/pull/"),
            "the pull request is in the hub's repo",
        )
        _check((pull.head, pull.base) == (change.branch, brain_origin.default_branch), "refs")
        _check((pull.title, pull.body) == (change.title, change.body), "the change's text")

    def test_archives_note_with_reason_when_rejected(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        change = _rejection(brain_origin)

        brain_change_requests.reject(change)

        archived = brain_origin.file_on(change.branch, _in_brain(ARCHIVED))
        _check(archived is not None, "the note is archived on the branch")
        fields = split_frontmatter(archived or "").fields
        _check(fields.get("rejected_reason") == "Duplicate of x", "the reason is recorded")
        _check(brain_origin.file_on(change.branch, _in_brain(NOTE)) is None, "inbox note moved")
        _check(
            brain_origin.file_on(brain_origin.default_branch, _in_brain(NOTE)) == NOTE_TEXT,
            "the default branch keeps the note",
        )

    def test_refuses_note_when_absent_from_default_branch(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        change = _change(brain_origin)

        _refused(lambda: brain_change_requests.accept(change), brain_origin)

    def test_refuses_destination_when_taken(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        brain_origin.put_on_default(_in_brain(ACCEPTED), "# Taken\n")
        change = _change(brain_origin)

        _refused(lambda: brain_change_requests.accept(change), brain_origin)

    def test_adopts_open_pull_request_when_branch_exists(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        change = _change(brain_origin)
        first = brain_change_requests.accept(change)
        head = brain_origin.head_commit(change.branch)

        again = brain_change_requests.accept(change)

        _check(again == first, "a retry returns the pull request already open for the branch")
        _check(len(brain_origin.pull_requests()) == 1, "a retry opens no second pull request")
        _check(brain_origin.head_commit(change.branch) == head, "the branch is kept as it was")

    def test_refuses_destination_when_under_decisions(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        change = _change(brain_origin, destination="decisions/testing-x.md")

        _refused(lambda: brain_change_requests.accept(change), brain_origin)

    def test_refuses_rejection_when_destination_not_archive(
        self, brain_change_requests: BrainChangeRequests, brain_origin: BrainOrigin
    ) -> None:
        brain_origin.put_on_default(_in_brain(NOTE), NOTE_TEXT)
        change = _rejection(brain_origin).model_copy(update={"destination": ACCEPTED})

        _refused(lambda: brain_change_requests.reject(change), brain_origin)
