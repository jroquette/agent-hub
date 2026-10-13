"""The read-only TrackerReader port and the issue summaries it returns (ADR 0025).

Separate from ``TrackerClient`` so the app gets no write method. A summary is metadata only:
never an issue's description, comments or attachments. Every failure raises ``TrackerError``
with a ``kind`` (``TrackerFailure``).
"""

from collections.abc import Sequence
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

# The most ids one ``issue_summaries`` call takes; more raise ``TrackerError(kind="too_many")``.
MAX_READ_IDS: Final = 200
# The most relations a summary keeps per direction; beyond, ``relations_truncated`` is True.
MAX_RELATIONS: Final = 50

# Linear's ``WorkflowState.type`` values (``tracker_client.STATE_TYPES``), as a type.
type IssueStateType = Literal[
    "triage", "backlog", "unstarted", "started", "completed", "canceled", "duplicate"
]


class IssueState(BaseModel):
    """An issue's workflow state: its ``name`` in the team and Linear's state ``type``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: IssueStateType


class IssueSummary(BaseModel):
    """What the app shows of one issue; ``id`` is the identifier, such as ``DEM-1``.

    ``title`` and ``assignee`` (a display name, None when unassigned) are untrusted text.
    ``priority`` is Linear's 0 (none) to 4 (low), 1 being urgent; ``estimate`` is None when not
    estimated. ``blocks`` names the issues this one blocks and ``blocked_by`` its blockers, in no
    defined order; ``relations_truncated`` is True when a direction had more than
    ``MAX_RELATIONS`` (the first ``MAX_RELATIONS`` the tracker returned are kept).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    state: IssueState
    assignee: str | None
    url: str
    priority: int | None = Field(ge=0, le=4)
    estimate: float | None
    blocks: tuple[str, ...]
    blocked_by: tuple[str, ...]
    relations_truncated: bool = False


class TicketSnapshot(BaseModel):
    """One read of the tracker.

    ``summaries`` holds the ids found, in the order first asked; ``missing`` the ids the tracker
    does not know, in the same order; ``external`` the blockers of those issues that were not
    asked for, sorted by id, read from the same relations (so they carry no relations of their
    own: ``blocks`` and ``blocked_by`` are empty).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summaries: tuple[IssueSummary, ...]
    missing: tuple[str, ...]
    external: tuple[IssueSummary, ...]


class TrackerReader(Protocol):
    """Reads issue summaries from a task tracker; never writes."""

    def issue_summaries(self, ids: Sequence[str]) -> TicketSnapshot:
        """The summaries of ``ids`` (duplicates read once), at most ``MAX_READ_IDS`` of them.

        An unknown or malformed id goes to ``missing``. Every failure raises ``TrackerError``
        with its ``kind``; more than ``MAX_READ_IDS`` distinct ids raise ``too_many`` before any
        request.
        """
        ...
