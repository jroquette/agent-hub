"""The report of a run through the tracker port: its writes in order, stopping at the first
that fails (spec D8). No write is retried."""

from collections.abc import Sequence
from typing import NamedTuple

from agent_hub.core.errors import TrackerError
from agent_hub.core.runner.report_writes import TrackerWrite
from agent_hub.core.tracker.tracker_client import TrackerClient


class ReportOutcome(NamedTuple):
    """The writes made, and the error that stopped the rest (None when all were made)."""

    done: int
    error: TrackerError | None


def apply_writes(client: TrackerClient, writes: Sequence[TrackerWrite]) -> ReportOutcome:
    """Make each write through ``client``, in order; the first ``TrackerError`` stops them."""
    for index, write in enumerate(writes):
        issue_id, value = write.arguments
        operation = getattr(client, write.operation)
        try:
            operation(issue_id, value)
        except TrackerError as error:
            return ReportOutcome(done=index, error=error)
    return ReportOutcome(done=len(writes), error=None)
