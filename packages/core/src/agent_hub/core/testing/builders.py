"""Builders of synthetic domain objects for tests; fixtures never come from real transcripts."""

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import uuid4

from agent_hub.core.events.event import Event


def an_event(**overrides: object) -> Event:
    """Build a valid synthetic event; ``source_id`` is unique per call unless overridden."""
    fields: dict[str, object] = {
        "project": "demo",
        "session": "session-1",
        "type": "tool.call",
        "timestamp": datetime(2026, 9, 27, 10, 0, 0, 123456, tzinfo=UTC),
        "source": "claude_code",
        "source_id": f"evt-{uuid4().hex}",
        "payload": {"tool": "search", "input": {"terms": ["alpha", "beta"], "limit": 3}},
    }
    return Event.model_validate(fields | overrides)


def events_to_jsonl(events: Iterable[Event]) -> str:
    """Write events as JSON Lines: one event per line, each line ending in a newline."""
    return "".join(f"{event.model_dump_json()}\n" for event in events)
