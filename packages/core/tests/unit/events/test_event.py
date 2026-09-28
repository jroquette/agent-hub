from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.events.event import Event, EventKey, EventSource, EventType

SPEC_TYPES = [
    "session.start",
    "session.end",
    "tool.call",
    "tool.result",
    "message",
    "reasoning",
    "decision",
    "gate.request",
    "gate.result",
    "learning.proposed",
    "learning.accepted",
]
SPEC_SOURCES = ["claude_code", "transcript", "otel", "executor", "github", "linear"]
REQUIRED_FIELDS = ["project", "session", "type", "timestamp", "source", "source_id"]


def required_fields() -> dict[str, Any]:
    return {
        "project": "demo",
        "session": "session-1",
        "type": "tool.call",
        "timestamp": "2026-09-27T10:00:00+00:00",
        "source": "claude_code",
        "source_id": "evt-1",
    }


def test_applies_defaults_when_only_required_fields_given() -> None:
    event = Event.model_validate(required_fields())

    assert event.payload == {}
    assert event.repo is None
    assert event.agent is None
    assert event.workflow is None
    assert event.step is None


def test_raises_when_field_assigned_after_validation() -> None:
    event = Event.model_validate(required_fields())

    with pytest.raises(ValidationError):
        event.project = "other"  # type: ignore[misc]


def test_normalizes_to_utc_when_timestamp_has_offset() -> None:
    event = Event.model_validate(required_fields() | {"timestamp": "2026-09-27T10:00:00+02:00"})

    assert event.timestamp == datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
    assert event.timestamp.isoformat() == "2026-09-27T08:00:00+00:00"
    assert event.timestamp.tzinfo == UTC


def test_rejects_timestamp_when_offset_missing() -> None:
    with pytest.raises(ValidationError, match="timestamp"):
        Event.model_validate(required_fields() | {"timestamp": "2026-09-27T10:00:00"})


def test_rejects_timestamp_when_given_as_number() -> None:
    with pytest.raises(ValidationError, match="timestamp"):
        Event.model_validate(required_fields() | {"timestamp": 1790503200})


@pytest.mark.parametrize("event_type", SPEC_TYPES, ids=SPEC_TYPES)
def test_accepts_type_when_listed_in_spec(event_type: str) -> None:
    event = Event.model_validate(required_fields() | {"type": event_type})

    assert event.type == EventType(event_type)


@pytest.mark.parametrize("source", SPEC_SOURCES, ids=SPEC_SOURCES)
def test_accepts_source_when_listed_in_spec(source: str) -> None:
    event = Event.model_validate(required_fields() | {"source": source})

    assert event.source == EventSource(source)


@pytest.mark.parametrize(
    ("field", "value"), [("type", "tool.use"), ("source", "slack")], ids=["type", "source"]
)
def test_rejects_value_when_type_or_source_unknown(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        Event.model_validate(required_fields() | {field: value})


@pytest.mark.parametrize("field", REQUIRED_FIELDS, ids=REQUIRED_FIELDS)
def test_rejects_event_when_required_field_missing(field: str) -> None:
    data = required_fields()
    del data[field]

    with pytest.raises(ValidationError, match=field):
        Event.model_validate(data)


def test_rejects_event_when_unknown_field_present() -> None:
    with pytest.raises(ValidationError, match="colour"):
        Event.model_validate(required_fields() | {"colour": "blue"})


@pytest.mark.parametrize("payload", [[], "x", 1, None], ids=["array", "string", "number", "null"])
def test_rejects_payload_when_not_json_object(payload: object) -> None:
    with pytest.raises(ValidationError, match="payload"):
        Event.model_validate(required_fields() | {"payload": payload})


@pytest.mark.parametrize("field", ["project", "session", "source_id"])
def test_rejects_string_when_empty(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        Event.model_validate(required_fields() | {field: ""})


def test_equals_event_when_same_instant_and_payload_in_other_key_order() -> None:
    first = Event.model_validate(
        required_fields()
        | {"timestamp": "2026-09-27T10:00:00+02:00", "payload": {"a": 1, "b": {"c": [1, 2]}}}
    )
    second = Event.model_validate(
        required_fields()
        | {"timestamp": "2026-09-27T08:00:00Z", "payload": {"b": {"c": [1, 2]}, "a": 1}}
    )

    assert first == second


def test_exposes_key_when_event_validated() -> None:
    event = Event.model_validate(required_fields())

    assert event.key == EventKey(source=EventSource.CLAUDE_CODE, source_id="evt-1")
