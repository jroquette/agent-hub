"""A bounded read of the event store: filters, a sequence window, a limit and an order."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.events.event import EventType, UtcTimestamp
from agent_hub.core.events.stored_event import StoredEvent

DEFAULT_QUERY_LIMIT = 200
MAX_QUERY_LIMIT = 10_000


class EventQuery(BaseModel):
    """Which stored events to read.

    Every filter is optional and they combine with "and": ``project``, ``session``, ``types``
    (empty = every type), ``since`` (inclusive) and ``until`` (exclusive) on the event
    timestamp, and the append-sequence window ``after_seq`` < seq < ``before_seq``. At most
    ``limit`` events come back, in append order (``asc``) or its reverse (``desc``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str | None = None
    session: str | None = None
    types: frozenset[EventType] = frozenset()
    since: UtcTimestamp | None = None
    until: UtcTimestamp | None = None
    after_seq: int | None = Field(default=None, ge=0)
    before_seq: int | None = Field(default=None, ge=0)
    limit: int = Field(default=DEFAULT_QUERY_LIMIT, ge=1, le=MAX_QUERY_LIMIT)
    order: Literal["asc", "desc"] = "asc"


class EventPage(BaseModel):
    """One page of a query: the events, and the ``after_seq`` of the next page (None at the end).

    ``next_after_seq`` is meaningful for ``asc`` queries; a ``desc`` reader pages with
    ``before_seq`` set to the smallest ``seq`` it received.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[StoredEvent, ...]
    next_after_seq: int | None
