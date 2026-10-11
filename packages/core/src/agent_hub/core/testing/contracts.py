"""Contract test suites for the core ports.

Each suite runs against the in-memory fake and against the real adapter, so both honour the
same behaviour. A suite is a plain class: an implementation's ``tests/contract/`` provides the
suite's fixtures (``event_store``; ``tracker_client`` and ``tracker_backend``) and declares
``class Test<Implementation>(EventStoreContract)`` or
``class Test<Implementation>(TrackerClientContract)``.
"""

import copy
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial

from agent_hub.core.errors import EventConflictError, TrackerError
from agent_hub.core.events.event import Event, EventType
from agent_hub.core.events.event_query import EventQuery
from agent_hub.core.events.event_store import AppendResult, EventStore
from agent_hub.core.events.stored_event import UUID_TEXT_PATTERN
from agent_hub.core.testing.builders import an_event, an_issue
from agent_hub.core.testing.fakes import FakeTrackerBackend
from agent_hub.core.tracker.tracker_client import Issue, TrackerClient


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

    def test_appends_both_when_source_id_repeats_under_other_source(
        self, event_store: EventStore
    ) -> None:
        # The identity is the pair (source, source_id): ids from different sources may collide.
        first = an_event(source="claude_code", source_id="evt-shared", payload={"version": 1})
        second = an_event(source="transcript", source_id="evt-shared", payload={"version": 2})

        result = event_store.append([first, second])

        assert result == AppendResult(appended=2, duplicates=0)
        assert event_store.read_all() == [first, second]

    def test_appends_nothing_when_batch_empty(self, event_store: EventStore) -> None:
        result = event_store.append([])

        assert result == AppendResult(appended=0, duplicates=0)
        assert event_store.read_all() == []


_QUERY_START = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


def _query_fixture(event_store: EventStore) -> list[Event]:
    # Six events over two projects, two sessions and three types, one minute apart.
    events = [
        an_event(project="demo", session="s1", type="session.start", timestamp=_QUERY_START),
        an_event(project="demo", session="s1", timestamp=_QUERY_START + timedelta(minutes=1)),
        an_event(
            project="demo",
            session="s2",
            type="message",
            timestamp=_QUERY_START + timedelta(minutes=2),
        ),
        an_event(project="other", session="s1", timestamp=_QUERY_START + timedelta(minutes=3)),
        an_event(
            project="demo",
            session="s1",
            type="message",
            timestamp=_QUERY_START + timedelta(minutes=4),
        ),
        an_event(project="demo", session="s2", timestamp=_QUERY_START + timedelta(minutes=5)),
    ]
    event_store.append(events)
    return events


class EventReaderContract:
    """What every ``EventStore`` read does: bounded queries, lookups by id, the high-water mark.

    Runs with the same ``event_store`` fixture as ``EventStoreContract``.
    """

    def test_returns_events_in_append_order_when_query_unfiltered(
        self, event_store: EventStore
    ) -> None:
        events = _query_fixture(event_store)

        page = event_store.query(EventQuery())

        assert [stored.event for stored in page.items] == events
        seqs = [stored.seq for stored in page.items]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
        assert page.next_after_seq is None

    def test_mints_distinct_uuid_ids_when_events_appended(self, event_store: EventStore) -> None:
        _query_fixture(event_store)

        items = event_store.query(EventQuery()).items

        ids = [stored.event_id for stored in items]
        assert len(set(ids)) == len(ids)
        assert all(re.fullmatch(UUID_TEXT_PATTERN, event_id) for event_id in ids)
        assert all(stored.received_at is not None for stored in items)

    def test_filters_by_project_and_session_when_both_given(self, event_store: EventStore) -> None:
        events = _query_fixture(event_store)

        page = event_store.query(EventQuery(project="demo", session="s1"))

        assert [stored.event for stored in page.items] == [events[0], events[1], events[4]]

    def test_filters_by_types_when_types_given(self, event_store: EventStore) -> None:
        events = _query_fixture(event_store)

        page = event_store.query(
            EventQuery(types=frozenset({EventType.MESSAGE, EventType.SESSION_START}))
        )

        assert [stored.event for stored in page.items] == [events[0], events[2], events[4]]

    def test_keeps_since_and_drops_until_when_time_range_given(
        self, event_store: EventStore
    ) -> None:
        events = _query_fixture(event_store)

        page = event_store.query(
            EventQuery(
                since=_QUERY_START + timedelta(minutes=1),
                until=_QUERY_START + timedelta(minutes=4),
            )
        )

        assert [stored.event for stored in page.items] == events[1:4]

    def test_reads_sequence_window_when_after_and_before_seq_given(
        self, event_store: EventStore
    ) -> None:
        _query_fixture(event_store)
        seqs = [stored.seq for stored in event_store.query(EventQuery()).items]

        page = event_store.query(EventQuery(after_seq=seqs[1], before_seq=seqs[4]))

        assert [stored.seq for stored in page.items] == seqs[2:4]

    def test_pages_with_next_after_seq_when_limit_reached(self, event_store: EventStore) -> None:
        events = _query_fixture(event_store)

        first = event_store.query(EventQuery(limit=4))
        second = event_store.query(EventQuery(limit=4, after_seq=first.next_after_seq))

        assert [stored.event for stored in first.items] == events[:4]
        assert first.next_after_seq == first.items[-1].seq
        assert [stored.event for stored in second.items] == events[4:]
        assert second.next_after_seq is None

    def test_ends_paging_when_limit_equals_remaining_events(self, event_store: EventStore) -> None:
        _query_fixture(event_store)

        page = event_store.query(EventQuery(limit=6))

        assert len(page.items) == 6
        assert page.next_after_seq is None

    def test_returns_newest_first_when_order_desc(self, event_store: EventStore) -> None:
        events = _query_fixture(event_store)

        page = event_store.query(EventQuery(order="desc", limit=2))
        older = event_store.query(EventQuery(order="desc", limit=10, before_seq=page.items[-1].seq))

        assert [stored.event for stored in page.items] == [events[5], events[4]]
        assert page.next_after_seq is None
        assert [stored.event for stored in older.items] == list(reversed(events[:4]))

    def test_finds_stored_event_when_event_id_known(self, event_store: EventStore) -> None:
        _query_fixture(event_store)
        third = event_store.query(EventQuery()).items[2]

        assert event_store.find(third.event_id) == third

    def test_finds_nothing_when_event_id_unknown(self, event_store: EventStore) -> None:
        _query_fixture(event_store)

        assert event_store.find("01929a4e-6c1d-7f3a-9b2e-5d1c0a8e4f17") is None

    def test_reports_zero_high_water_mark_when_store_empty(self, event_store: EventStore) -> None:
        assert event_store.high_water_mark() == 0

    def test_moves_high_water_mark_to_last_seq_when_events_appended(
        self, event_store: EventStore
    ) -> None:
        _query_fixture(event_store)

        assert event_store.high_water_mark() == event_store.query(EventQuery()).items[-1].seq

    def test_keeps_high_water_mark_and_ids_when_duplicates_appended(
        self, event_store: EventStore
    ) -> None:
        events = _query_fixture(event_store)
        before = event_store.query(EventQuery()).items
        mark = event_store.high_water_mark()

        result = event_store.append(events)

        assert result == AppendResult(appended=0, duplicates=len(events))
        assert event_store.high_water_mark() == mark
        assert event_store.query(EventQuery()).items == before


def _expecting_tracker_error(call: Callable[[], object]) -> TrackerError:
    # Plain try/except instead of pytest.raises, as in _append_expecting_conflict.
    try:
        call()
    except TrackerError as error:
        return error
    msg = "expected TrackerError"
    raise AssertionError(msg)


def _issue_operations(
    tracker_client: TrackerClient, issue_id: str
) -> dict[str, Callable[[], object]]:
    # Every operation that takes an issue id, called with arguments that are valid for DEM-1.
    return {
        "get_issue": lambda: tracker_client.get_issue(issue_id),
        "move_state": lambda: tracker_client.move_state(issue_id, "In Progress"),
        "add_label": lambda: tracker_client.add_label(issue_id, "bug"),
        "remove_label": lambda: tracker_client.remove_label(issue_id, "agent-ready"),
        "comment": lambda: tracker_client.comment(issue_id, "A synthetic comment."),
    }


def _labels_unchanged(before: FakeTrackerBackend, after: FakeTrackerBackend) -> bool:
    return (before.team_labels, before.workspace_labels) == (
        after.team_labels,
        after.workspace_labels,
    )


def _sorted_labels(issue: Issue) -> Issue:
    # A tracker may return labels in any order: compare issues with their labels sorted.
    return issue.model_copy(update={"labels": tuple(sorted(issue.labels))})


def _without(issues: dict[str, Issue], issue_id: str) -> dict[str, Issue]:
    return {key: issue for key, issue in issues.items() if key != issue_id}


# The seeded backend (``a_seeded_tracker_backend``): DEM-1..3 are DEM's open agent-ready issues;
# DEM-4..6 are agent-ready in Done, Canceled and Duplicate; DEM-7 is open and unlabelled; OPS-1 is
# open and agent-ready in another team. DEM-1 carries agent-ready and demo-api.
_SEEDED_READY = frozenset({"DEM-1", "DEM-2", "DEM-3"})
# Ids just outside ISSUE_ID_PATTERN, several of them close to a seeded id.
_MALFORMED_IDS = (
    "dem-1",
    " DEM-1",
    "DEM-1\n",
    "DEM-01",
    "DEM-0",
    "DEM1",
    "1EM-1",
    "ABCDEFGHIJK-1",
    "DEM-1234567890",
    "",
)
_SEEDED_MALFORMED_IDS = ("DEM-01", "dem-1", " DEM-1", "ABCDEFGHIJK-1", "DEM-1234567890")


class TrackerClientContract:
    """What every ``TrackerClient`` does over the ``tracker_backend`` it reads and writes.

    ``tracker_backend`` is ``a_seeded_tracker_backend()``; the suite asserts on its state, never
    on what the client says it did, so it runs the same against the fake and an adapter whose
    fake server serves that backend. ``list_ready`` is unordered and compared as a set. An adapter's
    fake server serves an empty description the way its tracker does (null or absent), so the suite
    exercises the mapping to ``""``.
    """

    def test_lists_open_team_issues_with_label_when_ready_issues_listed(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # Excludes Done, Canceled and Duplicate (D-a), the unlabelled DEM-7 and OPS-1.
        ready = tracker_client.list_ready("DEM", "agent-ready")

        assert all(isinstance(issue, Issue) for issue in ready)
        assert len(ready) == len(_SEEDED_READY)
        assert {_sorted_labels(issue) for issue in ready} == {
            _sorted_labels(tracker_backend.issues[issue_id]) for issue_id in _SEEDED_READY
        }

    def test_lists_only_labelled_issue_when_listed_by_repo_label(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        ready = tracker_client.list_ready("DEM", "demo-api")

        assert [_sorted_labels(issue) for issue in ready] == [
            _sorted_labels(tracker_backend.issues["DEM-1"])
        ]

    def test_lists_only_that_team_when_other_team_listed(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        ready = tracker_client.list_ready("OPS", "agent-ready")

        assert [_sorted_labels(issue) for issue in ready] == [
            _sorted_labels(tracker_backend.issues["OPS-1"])
        ]

    def test_lists_nothing_when_team_or_label_unknown(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        assert tracker_client.list_ready("NOPE", "agent-ready") == []
        assert tracker_client.list_ready("DEM", "no-such-label") == []
        assert tracker_backend == before

    def test_lists_nothing_when_label_only_on_closed_issues(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        for issue_id in _SEEDED_READY:
            tracker_backend.issues[issue_id] = tracker_backend.issues[issue_id].model_copy(
                update={"state": "Done"}
            )

        assert tracker_client.list_ready("DEM", "agent-ready") == []

    def test_returns_seeded_issue_when_issue_read(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        for issue_id, seeded in tracker_backend.issues.items():
            assert _sorted_labels(tracker_client.get_issue(issue_id)) == _sorted_labels(seeded)

    def test_returns_seeded_description_when_issue_read(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # Explicit, so a change to how whole issues are compared cannot hide a lost description.
        for issue_id, seeded in tracker_backend.issues.items():
            assert tracker_client.get_issue(issue_id).description == seeded.description
        ready = [
            *tracker_client.list_ready("DEM", "agent-ready"),
            *tracker_client.list_ready("OPS", "agent-ready"),
        ]
        assert {issue.id for issue in ready} == {*_SEEDED_READY, "OPS-1"}
        for issue in ready:
            assert issue.description == tracker_backend.issues[issue.id].description

    def test_moves_issue_when_state_known(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        tracker_client.move_state("DEM-1", "In Progress")

        moved = _sorted_labels(before.issues["DEM-1"].model_copy(update={"state": "In Progress"}))
        assert _sorted_labels(tracker_backend.issues["DEM-1"]) == moved
        assert _sorted_labels(tracker_client.get_issue("DEM-1")) == moved
        assert _without(tracker_backend.issues, "DEM-1") == _without(before.issues, "DEM-1")

    def test_drops_issue_from_ready_when_moved_to_closed_state(
        self, tracker_client: TrackerClient
    ) -> None:
        tracker_client.move_state("DEM-2", "Duplicate")

        ready = tracker_client.list_ready("DEM", "agent-ready")

        assert {issue.id for issue in ready} == _SEEDED_READY - {"DEM-2"}

    def test_keeps_state_when_moved_to_current_state(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        tracker_client.move_state("DEM-1", "Todo")

        assert tracker_backend == before

    def test_returns_moved_when_issue_moved_only_if_unstarted(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # DEM-1 is in Todo, an unstarted state.
        before = copy.deepcopy(tracker_backend)

        moved = tracker_client.move_state("DEM-1", "In Progress", only_if_unstarted=True)

        assert moved is True
        expected = _sorted_labels(
            before.issues["DEM-1"].model_copy(update={"state": "In Progress"})
        )
        assert _sorted_labels(tracker_backend.issues["DEM-1"]) == expected
        assert _without(tracker_backend.issues, "DEM-1") == _without(before.issues, "DEM-1")
        assert tracker_backend.states == before.states
        assert _labels_unchanged(before, tracker_backend)
        assert tracker_backend.comments == before.comments

    def test_keeps_started_issue_when_moved_only_if_unstarted(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # DEM-2 is in In Progress, a started state.
        before = copy.deepcopy(tracker_backend)

        moved = tracker_client.move_state("DEM-2", "Todo", only_if_unstarted=True)

        assert moved is False
        assert tracker_backend == before

    def test_keeps_closed_issue_when_moved_only_if_unstarted(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # DEM-4 is in Done, a completed state.
        before = copy.deepcopy(tracker_backend)

        moved = tracker_client.move_state("DEM-4", "In Progress", only_if_unstarted=True)

        assert moved is False
        assert tracker_backend == before

    def test_skips_name_check_when_started_issue_moved_only_if_unstarted(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # "Shipped" is no state of DEM: a started issue is left alone before the name is checked.
        before = copy.deepcopy(tracker_backend)

        moved = tracker_client.move_state("DEM-2", "Shipped", only_if_unstarted=True)

        assert moved is False
        assert tracker_backend == before

    def test_raises_naming_state_when_unstarted_issue_moved_only_if_unstarted(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # DEM-1 is unstarted, so the flag does not skip the name check.
        before = copy.deepcopy(tracker_backend)

        error = _expecting_tracker_error(
            lambda: tracker_client.move_state("DEM-1", "Shipped", only_if_unstarted=True)
        )

        assert str(error).startswith("move_state DEM-1: ")
        assert "Shipped" in str(error)
        assert tracker_backend == before

    def test_keeps_state_when_unstarted_issue_moved_to_current_state_only_if_unstarted(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        moved = tracker_client.move_state("DEM-1", "Todo", only_if_unstarted=True)

        assert moved is False
        assert tracker_backend == before

    def test_returns_whether_moved_when_moved_only_if_unstarted_off(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # Unconditional: a started issue moves too, and the current state is a no-op.
        before = copy.deepcopy(tracker_backend)

        assert tracker_client.move_state("DEM-2", "Todo") is True
        assert tracker_backend.issues["DEM-2"].state == "Todo"
        assert tracker_client.move_state("DEM-3", "Todo") is False
        assert tracker_backend.issues["DEM-3"] == before.issues["DEM-3"]

    def test_adds_label_keeping_others_when_team_label_known(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        tracker_client.add_label("DEM-1", "bug")

        labelled = tracker_backend.issues["DEM-1"]
        assert sorted(labelled.labels) == ["agent-ready", "bug", "demo-api"]
        assert labelled.model_dump(exclude={"labels"}) == before.issues["DEM-1"].model_dump(
            exclude={"labels"}
        )
        assert _without(tracker_backend.issues, "DEM-1") == _without(before.issues, "DEM-1")
        assert _labels_unchanged(before, tracker_backend)

    def test_adds_label_keeping_others_when_workspace_label_known(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        tracker_client.add_label("DEM-7", "agent-failed")

        labelled = tracker_backend.issues["DEM-7"]
        assert labelled.labels == ("agent-failed",)
        assert labelled.model_dump(exclude={"labels"}) == before.issues["DEM-7"].model_dump(
            exclude={"labels"}
        )
        assert _without(tracker_backend.issues, "DEM-7") == _without(before.issues, "DEM-7")
        assert _labels_unchanged(before, tracker_backend)

    def test_adds_workspace_label_when_issue_of_other_team_labelled(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        tracker_client.add_label("OPS-1", "agent-failed")

        assert sorted(tracker_backend.issues["OPS-1"].labels) == ["agent-failed", "agent-ready"]
        assert _without(tracker_backend.issues, "OPS-1") == _without(before.issues, "OPS-1")
        assert _labels_unchanged(before, tracker_backend)

    def test_keeps_backend_when_present_label_added(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        tracker_client.add_label("DEM-1", "demo-api")

        assert tracker_backend == before

    def test_removes_label_keeping_others_when_label_present(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        tracker_client.remove_label("DEM-1", "agent-ready")

        unlabelled = tracker_backend.issues["DEM-1"]
        assert unlabelled.labels == ("demo-api",)
        assert unlabelled.model_dump(exclude={"labels"}) == before.issues["DEM-1"].model_dump(
            exclude={"labels"}
        )
        assert _without(tracker_backend.issues, "DEM-1") == _without(before.issues, "DEM-1")
        assert _labels_unchanged(before, tracker_backend)

    def test_keeps_backend_when_absent_label_removed(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        tracker_client.remove_label("DEM-1", "bug")

        assert tracker_backend == before

    def test_records_one_comment_when_issue_commented(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)
        body = "Synthetic comment:\n- first line\n- second line, \u00e9 and `code`"

        tracker_client.comment("DEM-2", body)

        assert tracker_backend.comments == [*before.comments, ("DEM-2", body)]
        assert tracker_backend.issues == before.issues

    def test_raises_naming_id_when_issue_unknown(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        for operation, call in _issue_operations(tracker_client, "DEM-999").items():
            error = _expecting_tracker_error(call)

            assert str(error).startswith(f"{operation} DEM-999: "), operation
        assert tracker_backend == before

    def test_raises_naming_state_when_state_unknown(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        error = _expecting_tracker_error(lambda: tracker_client.move_state("DEM-1", "Shipped"))

        assert str(error).startswith("move_state DEM-1: ")
        assert "Shipped" in str(error)
        assert tracker_backend == before

    def test_raises_naming_state_when_state_of_other_team(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # Duplicate is a DEM state; OPS has none.
        before = copy.deepcopy(tracker_backend)

        error = _expecting_tracker_error(lambda: tracker_client.move_state("OPS-1", "Duplicate"))

        assert str(error).startswith("move_state OPS-1: ")
        assert "Duplicate" in str(error)
        assert tracker_backend == before

    def test_raises_naming_label_when_label_of_other_team(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # demo-api and bug are DEM team labels, not workspace labels.
        before = copy.deepcopy(tracker_backend)

        for name in ("demo-api", "bug"):
            error = _expecting_tracker_error(partial(tracker_client.add_label, "OPS-1", name))

            assert str(error).startswith("add_label OPS-1: "), name
            assert name in str(error), name
        assert tracker_backend == before

    def test_raises_naming_label_when_added_label_unknown(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        error = _expecting_tracker_error(lambda: tracker_client.add_label("DEM-1", "no-such-label"))

        assert str(error).startswith("add_label DEM-1: ")
        assert "no-such-label" in str(error)
        assert tracker_backend == before

    def test_raises_naming_label_when_removed_label_unknown(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        before = copy.deepcopy(tracker_backend)

        error = _expecting_tracker_error(
            lambda: tracker_client.remove_label("DEM-1", "no-such-label")
        )

        assert str(error).startswith("remove_label DEM-1: ")
        assert "no-such-label" in str(error)
        assert tracker_backend == before

    def test_raises_naming_id_when_id_malformed(
        self, tracker_client: TrackerClient, tracker_backend: FakeTrackerBackend
    ) -> None:
        # Issues stored under malformed ids: only a check of the id before any lookup raises.
        for issue_id in _SEEDED_MALFORMED_IDS:
            tracker_backend.issues[issue_id] = an_issue(id=issue_id)
        before = copy.deepcopy(tracker_backend)

        for issue_id in _MALFORMED_IDS:
            for operation, call in _issue_operations(tracker_client, issue_id).items():
                error = _expecting_tracker_error(call)

                assert (error.operation, error.issue_id) == (operation, issue_id)
                assert "\n" not in str(error), (operation, issue_id)
        assert tracker_backend == before
