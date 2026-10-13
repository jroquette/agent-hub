"""The tracker writes that report a run, in the order ``hub run`` makes them (spec D8).

One report per run outcome (ADR 0030). The *outcome labels* are the failed label and the
blocked label (``tracker.blocked_label``, else the failed label); a label is removed only when
the issue read at ``PICKED`` carries it (E10: a label the tracker lacks would fail the write).

- delivered: move to the caller's review state (``tracker.states.review``), remove the outcome
  labels the issue carries, then the comment;
- no changes: remove the outcome labels the issue carries, then the comment;
- blocked: add the blocked label, remove the failed label when the issue carries it and it is
  not the blocked label, then the comment;
- failed: add the failed label, then the comment.

``hub run`` stops at the first write that fails and never retries one; a dry run prints each
write's ``call_line``.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_hub.core.hub_config.model import REVIEW_STATE as REVIEW_STATE
from agent_hub.core.tracker.tracker_client import Issue

type WriteOperation = Literal["move_state", "add_label", "remove_label", "comment"]


class TrackerWrite(BaseModel):
    """One ``TrackerClient`` write: the port operation and its arguments (the issue id first)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: WriteOperation
    arguments: tuple[str, str]


def success_writes(
    issue: Issue, *, review_state: str, failed_label: str, blocked_label: str, comment: str
) -> tuple[TrackerWrite, ...]:
    """The writes of a run that opened its PR, ``issue`` as read at ``PICKED``."""
    return (
        TrackerWrite(operation="move_state", arguments=(issue.id, review_state)),
        *_carried_removals(issue, (failed_label, blocked_label)),
        TrackerWrite(operation="comment", arguments=(issue.id, comment)),
    )


def no_changes_writes(
    issue: Issue, *, failed_label: str, blocked_label: str, comment: str
) -> tuple[TrackerWrite, ...]:
    """The writes of a run that ended with no commit, ``issue`` as read at ``PICKED``."""
    return (
        *_carried_removals(issue, (failed_label, blocked_label)),
        TrackerWrite(operation="comment", arguments=(issue.id, comment)),
    )


def blocked_writes(
    issue: Issue, *, failed_label: str, blocked_label: str, comment: str
) -> tuple[TrackerWrite, ...]:
    """The writes of a run whose session stopped for a human, ``issue`` as read at ``PICKED``."""
    stale = () if failed_label == blocked_label else (failed_label,)
    return (
        TrackerWrite(operation="add_label", arguments=(issue.id, blocked_label)),
        *_carried_removals(issue, stale),
        TrackerWrite(operation="comment", arguments=(issue.id, comment)),
    )


def failure_writes(*, issue_id: str, failed_label: str, comment: str) -> tuple[TrackerWrite, ...]:
    """The writes of a run that failed."""
    return (
        TrackerWrite(operation="add_label", arguments=(issue_id, failed_label)),
        TrackerWrite(operation="comment", arguments=(issue_id, comment)),
    )


def _carried_removals(issue: Issue, labels: tuple[str, ...]) -> tuple[TrackerWrite, ...]:
    """A ``remove_label`` for each distinct label of ``labels`` the issue carries, in order."""
    carried = dict.fromkeys(label for label in labels if label in issue.labels)
    return tuple(
        TrackerWrite(operation="remove_label", arguments=(issue.id, label)) for label in carried
    )


def call_line(write: TrackerWrite) -> str:
    """The write as a dry run shows it: ``move_state(DEM-1, In Review)``."""
    return f"{write.operation}({', '.join(write.arguments)})"
