"""An in-memory ``BrainChangeRequests`` over a fake hub ``origin`` (checked by
``BrainChangeRequestsContract``).

``FakeBrainOrigin`` keeps each branch's files (hub-relative path to text), its head commit and
the pull requests opened; ``InMemoryBrainChangeRequests`` applies a ``BrainChange`` to it as
the ``hub_git`` adapter does to a real ``origin``, with the same refusals. A branch already on
``origin`` (a retry after a partly finished action) is adopted when it has an open pull request
and replaced when it has none, as the adapter does.
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from agent_hub.core.brain.brain_path import (
    BRAIN_FOLDER,
    BrainPathError,
    accept_destination,
    archive_destination,
)
from agent_hub.core.brain.frontmatter import with_body, with_frontmatter
from agent_hub.core.learnings.brain_change_requests import (
    BrainChange,
    ChangeRequestConflictError,
    ChangeRequestFailedError,
    ChangeRequestResult,
)
from agent_hub.core.testing.brain_change_requests_contract import OpenedPullRequest, OriginCommit

DEMO_HUB_PATH = "/home/demo/demo-hub"
DEMO_HUB_REPO = "acme/demo-hub"


@dataclass(kw_only=True)
class FakeBrainOrigin:
    """A hub's ``origin`` in memory: files and head commit per branch, and pull requests."""

    hub_path: str = DEMO_HUB_PATH
    hub_repo: str = DEMO_HUB_REPO
    default_branch: str = "main"
    files: dict[str, dict[str, str]] = field(default_factory=dict)
    heads: dict[str, OriginCommit] = field(default_factory=dict)
    pulls: list[OpenedPullRequest] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.files.setdefault(self.default_branch, {})

    def put_on_default(self, path: str, text: str) -> None:
        """Commit ``text`` at ``path`` on the default branch."""
        self.files[self.default_branch][path] = text
        self.heads[self.default_branch] = OriginCommit(
            author_name="Demo Owner", author_email="owner@example.com", message=f"add {path}"
        )

    def file_on(self, branch: str, path: str) -> str | None:
        """The text at ``path`` on ``branch``."""
        return self.files.get(branch, {}).get(path)

    def branch_names(self) -> frozenset[str]:
        """The branches."""
        return frozenset(self.files)

    def head_commit(self, branch: str) -> OriginCommit | None:
        """The head commit of ``branch``."""
        return self.heads.get(branch)

    def pull_requests(self) -> tuple[OpenedPullRequest, ...]:
        """The pull requests opened so far."""
        return tuple(self.pulls)


def _hub_path(path: str) -> str:
    return f"{BRAIN_FOLDER}/{path}"


def _check_destination(change: BrainChange) -> None:
    note = PurePosixPath(change.note)
    try:
        allowed = (
            accept_destination(change.destination, note)
            if change.action == "accept"
            else archive_destination(note)
        )
    except BrainPathError as error:
        raise ChangeRequestConflictError(error.reason) from None
    if allowed != change.destination:
        raise ChangeRequestConflictError(f"Destination not allowed: brain/{change.destination}")


class InMemoryBrainChangeRequests:
    """A ``BrainChangeRequests`` over a ``FakeBrainOrigin``.

    ``unavailable`` plays an unusable hub (its reason); ``fail_step`` plays a failed git or gh
    step, after which nothing is left pushed (as the adapter deletes its branch). ``calls``
    records every change asked for.
    """

    def __init__(
        self,
        origin: FakeBrainOrigin,
        *,
        unavailable: str | None = None,
        fail_step: str | None = None,
    ) -> None:
        self.origin = origin
        self.unavailable = unavailable
        self.fail_step = fail_step
        self.calls: list[BrainChange] = []

    def availability(self, hub_path: str) -> str | None:
        """``unavailable``, whatever the hub."""
        del hub_path
        return self.unavailable

    def accept(self, change: BrainChange) -> ChangeRequestResult:
        """Move the note into the brain on a new branch and open its PR."""
        return self._open(change)

    def reject(self, change: BrainChange) -> ChangeRequestResult:
        """Archive the note with its reason on a new branch and open its PR."""
        return self._open(change)

    def _refuse(self, change: BrainChange) -> None:
        if self.unavailable is not None:
            raise ChangeRequestConflictError(self.unavailable)
        _check_destination(change)
        default = self.origin.files[self.origin.default_branch]
        if _hub_path(change.note) not in default:
            reason = f"Note not on origin/{self.origin.default_branch}: brain/{change.note}"
            raise ChangeRequestConflictError(reason)
        if _hub_path(change.destination) in default:
            raise ChangeRequestConflictError(f"Destination exists: brain/{change.destination}")

    def _adopted(self, change: BrainChange) -> ChangeRequestResult | None:
        """The open pull request of ``change.branch`` when the branch exists; without one the
        branch is deleted (it can only be a leftover of this action) and None returned."""
        if change.branch not in self.origin.files:
            return None
        for pull in self.origin.pulls:
            if pull.head == change.branch:
                return ChangeRequestResult(pr_url=pull.url, branch=change.branch)
        del self.origin.files[change.branch]
        self.origin.heads.pop(change.branch, None)
        return None

    def _open(self, change: BrainChange) -> ChangeRequestResult:
        self.calls.append(change)
        if self.unavailable is not None:
            raise ChangeRequestConflictError(self.unavailable)
        _check_destination(change)
        adopted = self._adopted(change)
        if adopted is not None:
            return adopted
        self._refuse(change)
        if self.fail_step is not None:
            raise ChangeRequestFailedError(step=self.fail_step)
        files = dict(self.origin.files[self.origin.default_branch])
        text = files.pop(_hub_path(change.note))
        if change.note_body is not None:
            text = with_body(text, change.note_body)
        files[_hub_path(change.destination)] = with_frontmatter(text, change.frontmatter)
        self.origin.files[change.branch] = files
        self.origin.heads[change.branch] = OriginCommit(
            author_name=change.author.name,
            author_email=change.author.email,
            message=change.commit_message,
        )
        url = f"https://github.com/{change.hub_repo}/pull/{len(self.origin.pulls) + 1}"
        self.origin.pulls.append(
            OpenedPullRequest(
                url=url,
                head=change.branch,
                base=self.origin.default_branch,
                title=change.title,
                body=change.body,
            )
        )
        return ChangeRequestResult(pr_url=url, branch=change.branch)
