"""The read side of the event store: bounded queries, one event by id, the high-water mark."""

from typing import Protocol

from agent_hub.core.events.event_query import EventPage, EventQuery
from agent_hub.core.events.stored_event import StoredEvent


class EventReader(Protocol):
    """Reads stored events; never changes them. The SQLite store and the fake implement it."""

    def query(self, query: EventQuery) -> EventPage:
        """The events matching ``query``, in its order, at most ``query.limit`` of them."""
        ...

    def find(self, event_id: str) -> StoredEvent | None:
        """The stored event with this storage id, or None."""
        ...

    def high_water_mark(self) -> int:
        """The largest append sequence stored, 0 when the store is empty.

        A duplicate append does not move it; readers poll it to learn that something changed.
        """
        ...
