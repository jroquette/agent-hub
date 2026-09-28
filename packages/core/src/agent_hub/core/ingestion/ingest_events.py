"""Ingest a batch of canonical events into the EventStore."""

from collections.abc import Sequence

from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult, EventStore


class IngestEvents:
    """Append a batch of canonical events, all-or-nothing, and report what was written."""

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store

    def execute(self, events: Sequence[Event]) -> AppendResult:
        """Append ``events``; an ``EventConflictError`` propagates and nothing is written.

        Secret redaction (SPEC) is not built yet; it goes here, before the append, so every
        source is redacted on the way in.
        """
        return self._event_store.append(events)
