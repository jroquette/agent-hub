"""In-memory fakes of the core ports, used by unit tests and checked by the contract suites."""

from collections.abc import Sequence

from agent_hub.core.events.append_plan import plan_append
from agent_hub.core.events.event import Event, EventKey
from agent_hub.core.events.event_store import AppendResult


class InMemoryEventStore:
    """An ``EventStore`` kept in memory; it plans the whole batch before changing anything."""

    def __init__(self) -> None:
        self._by_key: dict[EventKey, Event] = {}
        self._events: list[Event] = []

    def append(self, events: Sequence[Event]) -> AppendResult:
        """Append the new events of the batch; a conflict raises before any change."""
        plan = plan_append(events, self._by_key)
        for event in plan.new_events:
            # Event is frozen only shallowly: keep a copy, so the caller's payload stays theirs.
            stored = event.model_copy(deep=True)
            self._by_key[event.key] = stored
            self._events.append(stored)
        return AppendResult(appended=len(plan.new_events), duplicates=plan.duplicates)

    def read_all(self) -> list[Event]:
        """Return every stored event in the order it was appended."""
        return [event.model_copy(deep=True) for event in self._events]
