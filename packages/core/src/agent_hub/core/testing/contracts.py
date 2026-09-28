"""Contract test suites for the core ports.

Each suite runs against the in-memory fake and against the real adapter, so both honour the
same behaviour. A suite is a plain class: an implementation's ``tests/contract/`` provides an
``event_store`` fixture and declares ``class Test<Implementation>(EventStoreContract)``.
"""

from collections.abc import Sequence

from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult, EventStore
from agent_hub.core.testing.builders import an_event


def _append_expecting_conflict(
    event_store: EventStore, batch: Sequence[Event]
) -> EventConflictError:
    # Plain try/except instead of pytest.raises: core ships this suite without depending on pytest.
    try:
        event_store.append(batch)
    except EventConflictError as error:
        return error
    msg = "expected EventConflictError"
    raise AssertionError(msg)


class EventStoreContract:
    """What every ``EventStore`` does: append-only, idempotent by key, all-or-nothing."""

    def test_appends_all_when_keys_distinct(self, event_store: EventStore) -> None:
        batch = [
            an_event(),
            an_event(payload={"nested": {"list": [1, "two", None], "flag": True}, "n": 1.5}),
            an_event(type="message", repo="org/a", agent="coder", workflow="feature", step="plan"),
        ]

        result = event_store.append(batch)

        assert result == AppendResult(appended=3, duplicates=0)
        assert event_store.read_all() == batch

    def test_reports_duplicates_when_same_batch_appended_again(
        self, event_store: EventStore
    ) -> None:
        batch = [an_event(), an_event(), an_event()]
        event_store.append(batch)

        result = event_store.append(batch)

        assert result == AppendResult(appended=0, duplicates=3)
        assert len(event_store.read_all()) == len(batch)

    def test_counts_one_duplicate_when_batch_repeats_event(self, event_store: EventStore) -> None:
        event = an_event()

        result = event_store.append([event, event])

        assert result == AppendResult(appended=1, duplicates=1)
        assert event_store.read_all() == [event]

    def test_rejects_whole_batch_when_stored_key_has_other_content(
        self, event_store: EventStore
    ) -> None:
        stored = an_event(payload={"version": 1})
        event_store.append([stored])
        changed = an_event(source_id=stored.source_id, payload={"version": 2})

        conflict = _append_expecting_conflict(event_store, [an_event(), changed])

        assert (conflict.source, conflict.source_id) == (stored.source, stored.source_id)
        assert conflict.position == 1
        assert event_store.read_all() == [stored]

    def test_stores_nothing_when_batch_holds_conflicting_pair(
        self, event_store: EventStore
    ) -> None:
        first = an_event(payload={"version": 1})
        second = an_event(source_id=first.source_id, payload={"version": 2})

        conflict = _append_expecting_conflict(event_store, [first, second])

        assert (conflict.source, conflict.source_id) == (first.source, first.source_id)
        assert conflict.position == 1
        assert event_store.read_all() == []

    def test_counts_duplicate_when_same_instant_has_other_offset(
        self, event_store: EventStore
    ) -> None:
        stored = an_event(timestamp="2026-09-27T08:00:00+00:00", payload={"a": 1, "b": [2]})
        event_store.append([stored])
        same = an_event(
            source_id=stored.source_id,
            timestamp="2026-09-27T10:00:00+02:00",
            payload={"b": [2], "a": 1},
        )

        result = event_store.append([same])

        assert result == AppendResult(appended=0, duplicates=1)
        assert event_store.read_all() == [stored]

    def test_appends_nothing_when_batch_empty(self, event_store: EventStore) -> None:
        result = event_store.append([])

        assert result == AppendResult(appended=0, duplicates=0)
        assert event_store.read_all() == []
