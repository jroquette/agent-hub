from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.testing.builders import an_event

EVENT_ID = "01929a4e-6c1d-7f3a-9b2e-5d1c0a8e4f17"


def test_keeps_fields_when_valid_stored_event_built() -> None:
    event = an_event()
    received = datetime(2026, 10, 9, 14, 5, 42, tzinfo=UTC)

    stored = StoredEvent(seq=1, event_id=EVENT_ID, received_at=received, event=event)

    assert (stored.seq, stored.event_id, stored.received_at, stored.event) == (
        1,
        EVENT_ID,
        received,
        event,
    )


def test_accepts_null_received_at_when_row_predates_phase_two() -> None:
    stored = StoredEvent(seq=7, event_id=EVENT_ID, received_at=None, event=an_event())

    assert stored.received_at is None


def test_normalizes_to_utc_when_received_at_has_offset() -> None:
    received = datetime(2026, 10, 9, 16, 0, tzinfo=timezone(timedelta(hours=2)))

    stored = StoredEvent(seq=1, event_id=EVENT_ID, received_at=received, event=an_event())

    assert stored.received_at == datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
    assert stored.received_at is not None
    assert stored.received_at.tzinfo == UTC


@pytest.mark.parametrize("seq", [0, -1])
def test_rejects_seq_when_not_positive(seq: int) -> None:
    with pytest.raises(ValidationError, match="seq"):
        StoredEvent(seq=seq, event_id=EVENT_ID, received_at=None, event=an_event())


@pytest.mark.parametrize("event_id", ["", "not-a-uuid", "01929a4e6c1d7f3a9b2e5d1c0a8e4f17"])
def test_rejects_event_id_when_not_uuid_text(event_id: str) -> None:
    with pytest.raises(ValidationError, match="event_id"):
        StoredEvent(seq=1, event_id=event_id, received_at=None, event=an_event())


def test_raises_when_field_assigned_after_validation() -> None:
    stored = StoredEvent(seq=1, event_id=EVENT_ID, received_at=None, event=an_event())

    with pytest.raises(ValidationError):
        stored.seq = 2  # type: ignore[misc]
