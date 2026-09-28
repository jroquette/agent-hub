"""Builders of synthetic domain objects for tests; fixtures never come from real transcripts."""

import copy
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent_hub.core.events.event import Event

# The Example of docs/design/project-config.md, a synthetic project.
_HUB_DOCUMENT: dict[str, Any] = {
    "$schema": "./hub.schema.json",
    "schema_version": 1,
    "platform": {"version": "0.2.0"},
    "project": {
        "name": "demo",
        "hub_repo": "acme/demo-hub",
        "branch_prefix": "jdoe/",
        "author_name": "Jane Doe",
        "author_email": "jane@example.com",
    },
    "tracker": {"kind": "linear", "team": "DEM"},
    "repos": [
        {
            "dir": "demo-api",
            "github": "acme/demo-api",
            "check_fast": "make check-fast",
            "check": "make check",
        }
    ],
    "guard": {"ask_before_edit": ["demo-api/docs/adr"]},
}


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


def a_hub_document() -> dict[str, Any]:
    """Build a valid synthetic ``hub.json`` document as plain JSON data; a fresh copy per call."""
    return copy.deepcopy(_HUB_DOCUMENT)
