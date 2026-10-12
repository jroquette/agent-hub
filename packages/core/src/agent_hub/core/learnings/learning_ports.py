"""The two ports the learning routes depend on: reads with the hub's note, and decisions.

``ReadLearnings`` (reads) combines the folded learnings with the registered hub's inbox notes;
``DecideLearning`` (decisions) checks the learning, opens the hub PR through
``BrainChangeRequests`` and stores one ``control_plane`` event.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agent_hub.core.errors import AgentHubError
from agent_hub.core.learnings.brain_change_requests import CommitAuthor
from agent_hub.core.learnings.learning import Learning, LearningActionResult, LearningDetail
from agent_hub.core.readmodels.filters import LearningFilter
from agent_hub.core.readmodels.page import Page


class LearningHub(BaseModel):
    """What a decision needs of a project's registered hub: its checkout, its GitHub repo, the
    default branch, the branch prefix and the commit author (``hub.json`` with
    ``hub.local.json``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str
    path: str
    hub_repo: str
    default_branch: str
    branch_prefix: str
    author: CommitAuthor


class LearningConflictError(AgentHubError):
    """The learning cannot be decided as asked (already decided, target refused, another
    action running); ``pr_url`` is the open PR when one exists."""

    def __init__(self, reason: str, *, pr_url: str | None = None) -> None:
        self.reason = reason
        self.pr_url = pr_url
        super().__init__(reason)


class HubReadOnlyError(AgentHubError):
    """Learning actions are unavailable for this hub here (read-only mount, container image,
    no ``git`` or ``gh``, a remote not on GitHub); ``reason`` says which."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class LearningReads(Protocol):
    """Learnings with what the hub's inbox note says about them."""

    def list_learnings(self, learning_filter: LearningFilter) -> Page[Learning]:
        """Learnings matching the filter, each with its summary or why the note is unavailable."""
        ...

    def get_learning(self, learning_id: str) -> LearningDetail:
        """One learning with its note, suggested target and target choices."""
        ...


class LearningDecisions(Protocol):
    """Accept or reject a learning through a hub pull request."""

    def accept(self, learning_id: str, *, target: str) -> LearningActionResult:
        """Open a PR that moves the note to ``target`` (a folder or a ``.md`` path)."""
        ...

    def reject(self, learning_id: str, *, reason: str) -> LearningActionResult:
        """Open a PR that archives the note with ``reason``."""
        ...
