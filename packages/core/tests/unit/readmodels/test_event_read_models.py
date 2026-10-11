from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from agent_hub.core.events.event import Event, EventType
from agent_hub.core.events.event_query import EventPage, EventQuery
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels import event_read_models
from agent_hub.core.readmodels.cursor import InvalidCursorError
from agent_hub.core.readmodels.event_read_models import FoldedEventReadModels
from agent_hub.core.readmodels.filters import (
    ApprovalFilter,
    LearningFilter,
    PageRequest,
    RunFilter,
    Scope,
    SessionFilter,
)
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, EventReadModels
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.sessions.session import Session, SessionStatus
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_run_events,
    a_session_events,
    learning_events,
    usage_events,
    with_transcript_copies,
)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class CountingStore(InMemoryEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.queries = 0
        self.after: list[int | None] = []

    def query(self, query: EventQuery) -> EventPage:
        self.queries += 1
        self.after.append(query.after_seq)
        return super().query(query)


def _guard_ask(session: str, minutes: float) -> Event:
    return an_event(
        session=session,
        type="gate.request",
        timestamp=SCENARIO_START + timedelta(minutes=minutes),
        repo="demo-api",
        payload={"gate_id": f"toolu_ask_{session}", "kind": "guard_ask", "path": "docs/adr/x.md"},
    )


def _service(store: InMemoryEventStore, now: datetime) -> tuple[FoldedEventReadModels, Clock]:
    clock = Clock(now)
    service = FoldedEventReadModels(
        store, now=clock, hub_path_of={"demo": "/home/demo/demo-hub"}.get
    )
    return service, clock


@pytest.fixture
def store() -> InMemoryEventStore:
    store = InMemoryEventStore()
    store.append(
        [
            *with_transcript_copies(
                a_session_events(
                    "s-a",
                    tools=(
                        ("MultiEdit", {"path": "src/fold.py"}),
                        ("Bash", {"command": "make check"}),
                    ),
                    failed_tools=frozenset({1}),
                    run="1a2b3c4d",
                    step="implement",
                    attempt=1,
                )
            ),
            *usage_events("s-a", turns=((1000, 100, 0, 0),)),
            *a_session_events("s-b", start=SCENARIO_START + timedelta(minutes=50), ended=False),
            _guard_ask("s-b", 57.5),
            *a_session_events("s-c", project="other", start=SCENARIO_START + timedelta(hours=3)),
            *a_run_events("1a2b3c4d", loops=1, fails=True),
            *learning_events(session="s-a"),
        ]
    )
    return store


NOW = SCENARIO_START + timedelta(hours=1)


def test_implements_event_read_models_port_when_built(store: InMemoryEventStore) -> None:
    service: EventReadModels = _service(store, NOW)[0]

    assert service.get_session("s-a").id == "s-a"


def test_raises_not_found_naming_entity_when_id_unknown(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]
    calls = {
        "session": lambda: service.get_session("nope"),
        "run": lambda: service.get_run("nope"),
        "approval": lambda: service.get_approval("nope"),
        "learning": lambda: service.get_learning("nope"),
    }

    for entity, call in calls.items():
        with pytest.raises(EntityNotFoundError) as raised:
            call()
        assert (raised.value.entity, raised.value.entity_id) == (entity, "nope")
    for call in (
        lambda: service.session_summary("nope"),
        lambda: service.session_events("nope", types=frozenset(), page=PageRequest()),
        lambda: service.session_files("nope"),
        lambda: service.session_cost("nope"),
    ):
        with pytest.raises(EntityNotFoundError):
            call()


def test_pages_without_repeat_or_skip_when_events_appended_between_pages() -> None:
    store = InMemoryEventStore()
    for index in range(120):
        store.append(
            a_session_events(
                f"s-{index:03d}",
                tools=(("Read", {"path": "a.py"}),),
                start=SCENARIO_START + timedelta(minutes=index),
            )
        )
    service = _service(store, SCENARIO_START + timedelta(hours=5))[0]
    seen: list[str] = []
    cursor: str | None = None
    for page_number in range(10):
        page = service.list_sessions(SessionFilter(limit=50, cursor=cursor))
        seen.extend(session.id for session in page.items)
        store.append(
            [
                *a_session_events(f"late-{page_number}", start=SCENARIO_START + timedelta(hours=4)),
                an_event(session="s-000", timestamp=SCENARIO_START + timedelta(hours=4)),
            ]
        )
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 120
    assert seen == [f"s-{index:03d}" for index in reversed(range(120))]


def test_raises_invalid_cursor_when_cursor_damaged(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]

    with pytest.raises(InvalidCursorError):
        service.list_sessions(SessionFilter(cursor="garbage"))


def test_filters_sessions_when_filters_given(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]

    def ids(**fields: object) -> list[str]:
        page = service.list_sessions(SessionFilter.model_validate(fields))
        return [session.id for session in page.items]

    assert ids() == ["s-c", "s-b", "s-a"]
    assert ids(project="demo") == ["s-b", "s-a"]
    assert ids(status=SessionStatus.WAITING) == ["s-b"]
    assert ids(run_id="1a2b3c4d") == ["s-a"]
    assert ids(workflow="issue-to-pr") == ["s-a"]
    assert ids(tool="MultiEdit") == ["s-a"]
    assert ids(file="fold.py") == ["s-a"]
    assert ids(cost_min=Decimal("0.001")) == ["s-a"]
    assert ids(cost_max=Decimal("0.001")) == []
    assert ids(guard_denial=False) == ["s-c", "s-b", "s-a"]
    assert ids(sort="started_at") == ["s-a", "s-b", "s-c"]
    assert ids(sort="-cost") == ["s-a", "s-c", "s-b"]
    assert ids(sort="cost") == ["s-a", "s-b", "s-c"]
    assert ids(started_from=SCENARIO_START + timedelta(minutes=30)) == ["s-c", "s-b"]
    page = service.list_sessions(SessionFilter(limit=2))
    assert page.total_estimate == 3
    assert page.next_cursor is not None


def test_lists_session_views_when_session_known(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]

    summary = service.session_summary("s-a")
    files = service.session_files("s-a")
    cost = service.session_cost("s-a")
    events = service.session_events("s-a", types=frozenset(), page=PageRequest(limit=200))
    calls = service.session_events(
        "s-a", types=frozenset({EventType.TOOL_CALL}), page=PageRequest(limit=200)
    )

    assert 3 <= len(summary.lines) <= 5
    assert [change.path for change in files.items] == ["src/fold.py"]
    assert cost.total_usd == Decimal("0.006")
    assert cost.run_total_usd == Decimal("0.006")
    assert cost.budget_usd == Decimal(10)
    timestamps = [item.timestamp for item in events.items]
    assert timestamps == sorted(timestamps)
    assert sum(item.conflict for item in events.items) == 4
    assert any(item.merged_sources for item in events.items)
    assert all(item.latency_ms is not None for item in events.items)
    assert {item.type for item in calls.items} == {EventType.TOOL_CALL}
    assert len(calls.items) == 4


def test_pages_session_events_when_limit_smaller_than_events(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]
    first = service.session_events("s-a", types=frozenset(), page=PageRequest(limit=5))
    second = service.session_events(
        "s-a", types=frozenset(), page=PageRequest(limit=50, cursor=first.next_cursor)
    )

    ids = [item.event_id for item in [*first.items, *second.items]]
    assert len(ids) == len(set(ids)) == first.total_estimate
    assert second.next_cursor is None


def test_lists_runs_approvals_and_learnings_when_filtered(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]

    runs = service.list_runs(RunFilter(outcome="failed"))
    run = service.get_run("1a2b3c4d")
    approvals = service.list_approvals(ApprovalFilter())
    decided = service.list_approvals(ApprovalFilter(status="decided"))
    learnings = service.list_learnings(LearningFilter(status="proposed"))

    assert [item.id for item in runs.items] == ["1a2b3c4d"]
    assert service.list_runs(RunFilter(outcome="done")).items == ()
    assert service.list_runs(RunFilter(failure_stage=Stage.VERIFYING)).total_estimate == 1
    assert run.session_ids == ("s-a",)
    assert run.cost_source == "sessions"
    assert [item.id for item in approvals.items] == ["toolu_ask_s-b"]
    assert approvals.items[0].how_to_decide == "cd /home/demo/demo-hub && claude --resume s-b"
    assert service.get_approval("toolu_ask_s-b").status == "open"
    assert decided.items == ()
    assert [item.id for item in learnings.items] == ["learning-1"]
    assert service.get_learning("learning-1").source_session_id == "s-a"


def test_groups_live_tiles_when_scope_given(store: InMemoryEventStore) -> None:
    service, clock = _service(store, NOW)

    tiles = service.list_live_sessions(Scope(project="demo"))
    clock.now = SCENARIO_START + timedelta(hours=10)
    later = service.list_live_sessions(Scope())

    assert [(tile.id, tile.group) for tile in tiles.items] == [("s-b", "waiting")]
    assert later.items == ()


def test_counts_project_activity_and_needs_when_project_has_events(
    store: InMemoryEventStore,
) -> None:
    service = _service(store, NOW)[0]

    activity = service.project_activity("demo")
    empty = service.project_activity("unknown")
    needs = service.needs_you(Scope(project="demo"))
    counts = service.stream_counts()

    assert activity.live_sessions == 1
    assert activity.failed_runs_7d == 1
    assert activity.cost_period == Decimal("0.006")
    assert activity.cost_previous_period is None
    assert len(activity.cost_daily) == 7
    assert activity.runs_in_flight_by_stage == {}
    assert (empty.live_sessions, empty.last_activity_at, empty.cost_period) == (0, None, None)
    assert [item.kind for item in needs.items] == ["learning", "failed", "approval"]
    assert all(item.href.startswith("/") for item in needs.items)
    assert counts.approvals_open == 1
    assert counts.live_sessions == 1
    assert counts.failed_runs_7d == 1
    assert counts.learnings_proposed == 1


def test_lists_activity_newest_first_when_requested(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]

    items = service.activity(PageRequest()).items

    assert {item.kind for item in items} >= {"failed", "learning"}
    times = [item.at for item in items]
    assert times == sorted(times, reverse=True)


def test_searches_ids_paths_commands_and_tools_when_query_given(
    store: InMemoryEventStore,
) -> None:
    service = _service(store, NOW)[0]

    def kinds(query: str) -> set[str]:
        return {hit.kind for hit in service.search_events(query, PageRequest()).items}

    assert kinds("s-a") >= {"session"}
    assert kinds("fold.py") == {"file"}
    assert kinds("MAKE CHECK") == {"command"}
    assert kinds("edit") == {"tool"}
    assert kinds("1a2b") == {"run"}
    assert kinds("toolu_ask") == {"approval"}
    assert kinds("learning-1") == {"learning"}
    assert service.search_events("nothing-matches", PageRequest()).items == ()


def test_never_searches_payload_bodies_when_text_only_in_other_keys() -> None:
    store = InMemoryEventStore()
    store.append(
        [an_event(session="s-x", payload={"tool": "Bash", "error_line": "sentinel-text-9"})]
    )
    service = _service(store, NOW)[0]

    assert service.search_events("sentinel-text-9", PageRequest()).items == ()


def test_reuses_loaded_events_when_store_unchanged(store: InMemoryEventStore) -> None:
    counting = CountingStore()
    counting.append(store.read_all())
    service = _service(counting, NOW)[0]

    service.list_sessions(SessionFilter())
    loaded = counting.queries
    service.list_runs(RunFilter())
    service.get_session("s-a")

    assert counting.queries == loaded
    counting.append([an_event(session="s-new")])
    assert service.get_session("s-new").id == "s-new"
    assert counting.queries > loaded


def test_reads_only_new_events_when_store_grows(store: InMemoryEventStore) -> None:
    counting = CountingStore()
    counting.append(store.read_all())
    service = _service(counting, NOW)[0]
    service.list_sessions(SessionFilter())
    mark = counting.high_water_mark()
    counting.after.clear()

    counting.append([an_event(session="s-new")])
    session = service.get_session("s-new")

    assert session.id == "s-new"
    assert counting.after == [mark]
    assert service.get_session("s-a").id == "s-a"


def test_refolds_only_changed_session_when_store_grows(
    store: InMemoryEventStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    folded: list[str] = []
    fold = event_read_models.fold_session

    def counting_fold(events: Sequence[StoredEvent], **options: Any) -> Session:
        folded.append(events[0].event.session)
        return fold(events, **options)

    monkeypatch.setattr(event_read_models, "fold_session", counting_fold)
    service = _service(store, NOW)[0]
    before = service.get_session("s-a")
    folded.clear()

    store.append([an_event(session="s-b", timestamp=NOW - timedelta(minutes=1))])
    after = service.get_session("s-a")
    changed = service.get_session("s-b")

    assert folded == ["s-b"]
    assert after == before
    assert changed.last_activity_at == NOW - timedelta(minutes=1)
