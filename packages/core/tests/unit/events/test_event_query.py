from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_hub.core.events.event import EventType
from agent_hub.core.events.event_query import MAX_QUERY_LIMIT, EventPage, EventQuery
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.testing.builders import an_event


def test_applies_defaults_when_no_field_given() -> None:
    query = EventQuery()

    assert query.project is None
    assert query.session is None
    assert query.types == frozenset()
    assert (query.since, query.until) == (None, None)
    assert (query.after_seq, query.before_seq) == (None, None)
    assert query.limit == 200
    assert query.order == "asc"


def test_keeps_filters_when_every_field_given() -> None:
    since = datetime(2026, 10, 1, tzinfo=UTC)
    until = datetime(2026, 10, 2, tzinfo=UTC)

    query = EventQuery(
        project="demo",
        session="session-1",
        types=frozenset({EventType.TOOL_CALL}),
        since=since,
        until=until,
        after_seq=10,
        before_seq=20,
        limit=MAX_QUERY_LIMIT,
        order="desc",
    )

    assert query.types == frozenset({EventType.TOOL_CALL})
    assert (query.since, query.until, query.after_seq, query.before_seq) == (since, until, 10, 20)
    assert (query.limit, query.order) == (10_000, "desc")


@pytest.mark.parametrize("limit", [0, -1, MAX_QUERY_LIMIT + 1])
def test_rejects_limit_when_out_of_bounds(limit: int) -> None:
    with pytest.raises(ValidationError, match="limit"):
        EventQuery(limit=limit)


@pytest.mark.parametrize("field", ["after_seq", "before_seq"])
def test_rejects_seq_bound_when_negative_out_of_bounds(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        EventQuery.model_validate({field: -1})


def test_rejects_order_when_value_unknown_out_of_bounds() -> None:
    with pytest.raises(ValidationError, match="order"):
        EventQuery.model_validate({"order": "random"})


def test_rejects_timestamp_when_naive_out_of_bounds() -> None:
    with pytest.raises(ValidationError, match="since"):
        EventQuery.model_validate({"since": "2026-10-01T00:00:00"})


def test_keeps_items_when_page_built() -> None:
    stored = StoredEvent(
        seq=3,
        event_id="01929a4e-6c1d-7f3a-9b2e-5d1c0a8e4f17",
        received_at=None,
        event=an_event(),
    )

    page = EventPage(items=(stored,), next_after_seq=3)

    assert page.items == (stored,)
    assert page.next_after_seq == 3
