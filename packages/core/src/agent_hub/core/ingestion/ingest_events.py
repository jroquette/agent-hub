"""Ingest a batch of canonical events into the EventStore, redacted on the way in."""

from collections.abc import Sequence

from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult, EventStore
from agent_hub.core.redaction.redact import redact_text, redact_value

# The free-text labels an event carries besides its payload (D10).
_REDACTED_LABELS = ("repo", "agent", "workflow", "step")


class IngestEvents:
    """Append a batch of canonical events, all-or-nothing, and report what was written.

    Every entry point (hooks, transcripts, run records, JSON Lines) goes through here, so every
    stored event is redacted (D10): each string of ``payload``, at any depth, and the labels
    ``repo``, ``agent``, ``workflow`` and ``step``. Redaction is idempotent, so a re-ingested
    event is still a duplicate.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store

    def execute(self, events: Sequence[Event]) -> AppendResult:
        """Append ``events`` redacted; an ``EventConflictError`` propagates, nothing written."""
        return self._event_store.append([redact_event(event) for event in events])


def redact_event(event: Event) -> Event:
    """``event`` with its payload and labels redacted (D10); other fields are kept."""
    update: dict[str, object] = {"payload": redact_value(dict(event.payload))}
    for label in _REDACTED_LABELS:
        value = getattr(event, label)
        if value is not None:
            update[label] = redact_text(value)
    return event.model_copy(update=update)
