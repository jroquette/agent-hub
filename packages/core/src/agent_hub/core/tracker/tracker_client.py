"""The TrackerClient port and the Issue it returns (Linear now, through an adapter)."""

import re
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

# An issue identifier: team key, a dash, a number (``DEM-1``). Match it with ``fullmatch``.
ISSUE_ID_PATTERN = re.compile(r"[A-Z][A-Z0-9]{0,9}-[1-9][0-9]{0,8}")

# Linear's ``WorkflowState.type`` values; ``duplicate`` included, as Linear's API answers it.
STATE_TYPES: Final = (
    "triage",
    "backlog",
    "unstarted",
    "started",
    "completed",
    "canceled",
    "duplicate",
)
# The types of a state no one has started work in: a conditional ``move_state``
# (``only_if_unstarted``) moves only from these.
UNSTARTED_STATE_TYPES: Final = ("triage", "backlog", "unstarted")
# The types of a closed state: done, canceled or duplicate.
CLOSED_STATE_TYPES: Final = ("completed", "canceled", "duplicate")


class Issue(BaseModel):
    """An issue as the workflow sees it; ``id`` is the tracker's identifier, such as ``DEM-1``.

    ``description`` is the issue's Markdown body as the tracker holds it, ``""`` when it has
    none (an adapter maps the tracker's null or absent body to ``""``); it is untrusted text.
    ``labels`` holds label names; the repo-routing label is one of them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    description: str
    state: str
    labels: tuple[str, ...]
    url: str


class TrackerClient(Protocol):
    """The operations the workflow needs from a task tracker.

    Every failure raises ``TrackerError``. In ``get_issue`` and the write operations, an
    unknown issue id, state name or label name raises it naming that value, and nothing
    changes; no state or label is ever created. ``list_ready`` filters, so an unknown team
    or label returns ``[]``.
    """

    def list_ready(self, team: str, label: str) -> list[Issue]:
        """Return the issues of ``team`` that carry ``label`` and are not done or canceled.

        An unknown team or label matches no issue and returns ``[]``.
        """
        ...

    def get_issue(self, issue_id: str) -> Issue:
        """Return the issue with the identifier ``issue_id``."""
        ...

    def move_state(
        self, issue_id: str, state_name: str, *, only_if_unstarted: bool = False
    ) -> bool:
        """Move the issue to the state named ``state_name``.

        True when the issue moved. Moving to the current state is a no-op (False). With
        ``only_if_unstarted``, an issue whose state type is not in ``UNSTARTED_STATE_TYPES`` is
        left as it is (False) and ``state_name`` is not checked. The check and the write are not
        atomic (a read, then a write), so a change made in between is not seen, as with labels.
        """
        ...

    def add_label(self, issue_id: str, name: str) -> None:
        """Add the label ``name``, keeping the others; a label already present is a no-op."""
        ...

    def remove_label(self, issue_id: str, name: str) -> None:
        """Remove the label ``name``, keeping the others; a label not present is a no-op."""
        ...

    def comment(self, issue_id: str, body: str) -> None:
        """Add one comment with ``body`` to the issue; never retried, as it is not idempotent."""
        ...
