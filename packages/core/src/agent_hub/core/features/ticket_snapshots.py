"""The ``TicketSnapshots`` port: tracker snapshots of a feature's tickets, cached (AGH-136 S2).

Only ``fetch`` may call the tracker; ``cached`` answers from what an earlier ``fetch`` kept
(the Features list and detail use it, Q6). Neither raises for a tracker failure: a
``SnapshotRead`` says what was served and why.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, Self

from agent_hub.core.errors import TrackerFailure
from agent_hub.core.features.feature_view import TicketsSource
from agent_hub.core.tracker.tracker_reader import TicketSnapshot

type TrackerTransport = Literal["api", "mcp"]


@dataclass(frozen=True, kw_only=True, slots=True)
class SnapshotRequest:
    """The tickets of one feature to read: the project, its hub's ``tracker.transport`` and the
    issue ids, sorted and unique (with the project, the cache key). Build it with ``of``."""

    project: str
    transport: TrackerTransport
    ids: tuple[str, ...]

    @classmethod
    def of(cls, *, project: str, transport: TrackerTransport, ids: Iterable[str]) -> Self:
        """The request with ``ids`` sorted and unique."""
        return cls(project=project, transport=transport, ids=tuple(sorted(set(ids))))


@dataclass(frozen=True, kw_only=True, slots=True)
class SnapshotRead:
    """What a ``TicketSnapshots`` call served.

    ``source`` is ``linear`` exactly when ``snapshot`` is set: fresh, or ``stale`` (the last good
    one kept after a failure), read at ``as_of``. Otherwise ``plan``: never read yet (a cold
    cache: ``failure`` None) or the read failed. ``failure`` is the last read's failure kind
    (``not_connected`` when there is no key or the transport is MCP), ``detail`` its one-line
    cause (never the key) and ``http_status`` the tracker's HTTP status, if it answered.
    """

    snapshot: TicketSnapshot | None
    source: TicketsSource
    stale: bool
    as_of: datetime | None
    failure: TrackerFailure | None
    detail: str | None
    http_status: int | None


class TicketSnapshots(Protocol):
    """Snapshots of tickets from the tracker, behind a cache."""

    def fetch(self, request: SnapshotRequest) -> SnapshotRead:
        """Read the tracker unless a fresh snapshot is cached; the only call that may reach it."""
        ...

    def cached(self, request: SnapshotRequest) -> SnapshotRead:
        """What the cache holds for ``request``; never reads the tracker."""
        ...
