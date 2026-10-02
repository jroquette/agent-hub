"""The tracker writes that report a run, in the order ``hub run`` makes them (spec D8).

Success: move to ``REVIEW_STATE``, remove the failed label when the issue read at ``PICKED``
carries it (E10: a label the tracker lacks would fail the write), then the comment. Failure:
add the failed label, then the comment. ``hub run`` stops at the first write that fails and
never retries one; a dry run prints each write's ``call_line``.
"""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from agent_hub.core.tracker.tracker_client import Issue

REVIEW_STATE: Final = "In Review"

type WriteOperation = Literal["move_state", "add_label", "remove_label", "comment"]


class TrackerWrite(BaseModel):
    """One ``TrackerClient`` write: the port operation and its arguments (the issue id first)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: WriteOperation
    arguments: tuple[str, str]


def success_writes(
    issue: Issue, *, review_state: str, failed_label: str, comment: str
) -> tuple[TrackerWrite, ...]:
    """The writes of a run that opened its PR, ``issue`` as read at ``PICKED``."""
    writes = [TrackerWrite(operation="move_state", arguments=(issue.id, review_state))]
    if failed_label in issue.labels:
        writes.append(TrackerWrite(operation="remove_label", arguments=(issue.id, failed_label)))
    writes.append(TrackerWrite(operation="comment", arguments=(issue.id, comment)))
    return tuple(writes)


def failure_writes(*, issue_id: str, failed_label: str, comment: str) -> tuple[TrackerWrite, ...]:
    """The writes of a run that failed."""
    return (
        TrackerWrite(operation="add_label", arguments=(issue_id, failed_label)),
        TrackerWrite(operation="comment", arguments=(issue_id, comment)),
    )


def call_line(write: TrackerWrite) -> str:
    """The write as a dry run shows it: ``move_state(DEM-1, In Review)``."""
    return f"{write.operation}({', '.join(write.arguments)})"
