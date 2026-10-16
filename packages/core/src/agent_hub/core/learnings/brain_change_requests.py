"""The port that turns a learning decision into a hub pull request (ADR 0024, S6).

``DecideLearning`` builds a ``BrainChange`` (redacted title, body and reason; destination and
branch from the brain rules) and calls the port; the ``hub_git`` adapter runs ``git`` and
``gh`` in a temporary clone of the hub's ``origin``, pushes one new branch and opens the PR.
Nothing is ever written to the default branch or to the user's checkout.
"""

from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_hub.core.errors import AgentHubError

type ChangeAction = Literal["accept", "reject"]


class CommitAuthor(BaseModel):
    """Who the commit is by: the hub's effective identity (ADR 0016), never an agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    email: str = Field(min_length=3)


class BrainChange(BaseModel):
    """One learning decision as a hub change: move ``note`` to ``destination`` with
    ``frontmatter`` set, on the new ``branch``, then open a PR from it to ``default_branch``.

    ``note`` and ``destination`` are relative to the hub's ``brain/``; ``hub_repo`` is the
    GitHub ``owner/name`` of the hub's ``origin``. ``title``, ``body`` and ``commit_message``
    are already redacted. ``note_body``, when set, replaces the note's text after its
    frontmatter in the same commit: the edit the human made before accepting.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hub_path: str = Field(min_length=1)
    hub_repo: str = Field(min_length=3)
    default_branch: str = Field(min_length=1)
    action: ChangeAction
    note: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    frontmatter: dict[str, str]
    note_body: str | None = None
    author: CommitAuthor
    branch: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str
    commit_message: str = Field(min_length=1)

    @model_validator(mode="after")
    def _branch_is_not_default(self) -> Self:
        if self.branch == self.default_branch:
            raise ValueError("branch must not be the default branch")
        return self


class ChangeRequestResult(BaseModel):
    """The pull request a change opened and the branch it was pushed on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pr_url: str
    branch: str


class ChangeRequestError(AgentHubError):
    """Base of the errors a ``BrainChangeRequests`` adapter raises."""


class ChangeRequestConflictError(ChangeRequestError):
    """The change cannot be made as asked (note absent from the default branch, destination
    taken, hub unusable); ``reason`` names it. Nothing was pushed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ChangeRequestFailedError(ChangeRequestError):
    """A ``git`` or ``gh`` step failed; ``step`` names it. No git or gh output is kept."""

    def __init__(self, *, step: str) -> None:
        self.step = step
        super().__init__(f"could not open the pull request: step {step} failed")


class ChangeRequestTimeoutError(ChangeRequestError):
    """The whole action passed its deadline."""

    def __init__(self) -> None:
        super().__init__("could not open the pull request in time")


class RefspecRefusedError(ChangeRequestError):
    """A push was refused before git ran: the default branch, a forced or deleting refspec,
    a force flag, or a branch outside the learning names."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class BrainChangeRequests(Protocol):
    """Opens hub pull requests for learning decisions.

    A retry may find the change's branch already on ``origin`` (an earlier action stopped after
    the push or the pull request): its open pull request is adopted and returned; with none open
    the branch is replaced."""

    def availability(self, hub_path: str) -> str | None:
        """Why actions are unavailable for this hub ("Hub is read-only here", "Hub remote is
        not on GitHub", ...), or None when they are available."""
        ...

    def accept(self, change: BrainChange) -> ChangeRequestResult:
        """Push a branch that moves the note into the brain and open its PR."""
        ...

    def reject(self, change: BrainChange) -> ChangeRequestResult:
        """Push a branch that archives the note with the reason and open its PR."""
        ...
