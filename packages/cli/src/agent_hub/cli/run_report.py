"""The report of a run through the tracker port: its writes in order, stopping at the first
that fails (spec D8). No write is retried."""

from collections.abc import Sequence
from typing import NamedTuple

from agent_hub.core.errors import TrackerError
from agent_hub.core.runner.report_writes import TrackerWrite
from agent_hub.core.tracker.tracker_client import TrackerClient


class ReportOutcome(NamedTuple):
    """The writes made, the error that stopped the rest (None when all were made), and what
    the writes cost."""

    done: int
    error: TrackerError | None
    cost_usd: float


def apply_writes(client: TrackerClient, writes: Sequence[TrackerWrite]) -> ReportOutcome:
    """Make each write through ``client``, in order; the first ``TrackerError`` stops them."""
    cost = 0.0
    for index, write in enumerate(writes):
        issue_id, value = write.arguments
        operation = getattr(client, write.operation)
        try:
            operation(issue_id, value)
        except TrackerError as error:
            return ReportOutcome(done=index, error=error, cost_usd=cost + tracker_cost(client))
        cost += tracker_cost(client)
    return ReportOutcome(done=len(writes), error=None, cost_usd=cost)


def tracker_cost(client: TrackerClient) -> float:
    """What the client's last port operation cost: the MCP adapter's ``last_cost_usd`` (Q-10);
    0 for an adapter that spends no tokens."""
    cost = getattr(client, "last_cost_usd", 0.0)
    return float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else 0.0
