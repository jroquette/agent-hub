from datetime import UTC, datetime, timedelta, timezone

import pytest

from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.append_plan import AppendPlan, plan_append
from agent_hub.core.events.event import Event, EventKey
from agent_hub.core.testing.builders import an_event


def stored_by_key(*events: Event) -> dict[EventKey, Event]:
    return {event.key: event for event in events}


def test_marks_all_new_when_keys_distinct() -> None:
    batch = [an_event(), an_event(), an_event()]

    plan = plan_append(batch, {})

    assert plan == AppendPlan(new_events=tuple(batch), duplicates=0)


def test_counts_duplicate_when_identical_event_stored() -> None:
    stored = an_event()
    fresh = an_event()

    plan = plan_append([stored, fresh], stored_by_key(stored))

    assert plan == AppendPlan(new_events=(fresh,), duplicates=1)


def test_counts_duplicate_when_identical_event_repeated_in_batch() -> None:
    event = an_event()

    plan = plan_append([event, event], {})

    assert plan == AppendPlan(new_events=(event,), duplicates=1)


def test_raises_conflict_with_position_when_stored_event_differs() -> None:
    stored = an_event(payload={"v": 1})
    changed = an_event(source_id=stored.source_id, payload={"v": 2})

    with pytest.raises(EventConflictError) as caught:
        plan_append([an_event(), changed], stored_by_key(stored))

    assert (caught.value.source, caught.value.source_id) == (stored.source, stored.source_id)
    assert caught.value.position == 1


def test_raises_conflict_with_position_when_batch_events_differ() -> None:
    first = an_event(payload={"v": 1})
    second = an_event(source_id=first.source_id, payload={"v": 2})

    with pytest.raises(EventConflictError) as caught:
        plan_append([first, an_event(), second], {})

    assert caught.value.source_id == first.source_id
    assert caught.value.position == 2


def test_counts_duplicate_when_same_instant_has_other_offset() -> None:
    instant = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
    stored = an_event(timestamp=instant)
    same = an_event(
        source_id=stored.source_id,
        timestamp=instant.astimezone(timezone(timedelta(hours=2))),
    )

    plan = plan_append([same], stored_by_key(stored))

    assert plan == AppendPlan(new_events=(), duplicates=1)


def test_keeps_input_order_when_new_events_planned() -> None:
    stored = an_event()
    first, second, third = an_event(), an_event(), an_event()

    plan = plan_append([third, stored, first, second], stored_by_key(stored))

    assert plan.new_events == (third, first, second)
