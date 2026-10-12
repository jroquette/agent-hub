"""Ingest a batch of canonical events into the EventStore, redacted on the way in."""

from collections.abc import Sequence

from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult, EventStore
from agent_hub.core.events.payload_keys import kept_payload
from agent_hub.core.redaction.redact import redact_text, redact_value

# The free-text labels an event carries besides its payload (D10).
_REDACTED_LABELS = ("repo", "agent", "workflow", "step")


class IngestEvents:
    """Append a batch of canonical events, all-or-nothing, and report what was written.

    Every entry point (hooks, transcripts, run records, JSON Lines) goes through here, so every
    stored event is redacted (D10): each string of ``payload``, at any depth, and the labels
    ``repo``, ``agent``, ``workflow`` and ``step``. After redaction the payload is trimmed to the
    keys its type may store (D11, ``payload_keys``): any other key is dropped, not rejected, so
    no entry point stores body text. Both steps are idempotent, so a re-ingested event is still
    a duplicate.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store

    def execute(self, events: Sequence[Event]) -> AppendResult:
        """Append ``events`` redacted; an ``EventConflictError`` propagates, nothing written."""
        return self._event_store.append([redact_event(event) for event in events])


def redact_event(event: Event) -> Event:
    """``event`` redacted (D10) and trimmed to its type's payload keys (D11); other fields kept."""
    redacted = redact_value(dict(event.payload))
    payload = kept_payload(event.type, redacted) if isinstance(redacted, dict) else {}
    update: dict[str, object] = {"payload": payload}
    for label in _REDACTED_LABELS:
        value = getattr(event, label)
        if value is not None:
            update[label] = redact_text(value)
    return event.model_copy(update=update)
