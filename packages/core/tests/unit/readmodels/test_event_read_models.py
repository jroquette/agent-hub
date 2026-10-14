from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from agent_hub.core.agent_sessions.links import AgentSessionLink
from agent_hub.core.events.event import MAX_ID_CHARS, Event, EventType
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
from agent_hub.core.sessions.fold_session import FoldedSession
from agent_hub.core.sessions.problem import ProblemKind, Resolution
from agent_hub.core.sessions.session import ProblemCounts, SessionStatus
from agent_hub.core.sessions.session_label import LabelRules
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_run_events,
    a_session_events,
    learning_events,
    shuffled,
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
        lambda: service.session_problems("nope"),
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


def test_fills_tile_fields_when_sessions_listed(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]

    listed = {s.id: s for s in service.list_sessions(SessionFilter()).items}
    [tile] = service.list_live_sessions(Scope(project="demo")).items
    one = service.get_session("s-b")

    waiting = listed["s-b"]
    assert (
        waiting.waiting_reason,
        waiting.last_action,
        waiting.last_tool,
        waiting.needs_you_problem,
        waiting.failing_notice,
    ) == (
        tile.waiting_reason,
        tile.last_action,
        tile.last_tool,
        tile.needs_you_problem,
        tile.failing_notice,
    )
    assert waiting.waiting_reason == "Guard ask"
    assert waiting.sparkline_60s == ()
    assert one == waiting
    ended = listed["s-a"]
    assert ended.last_tool is not None
    assert ended.sparkline_60s is None


def test_folds_tile_fields_for_page_rows_only_when_page_smaller_than_matches(
    store: InMemoryEventStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(store, NOW)[0]
    calls: list[str] = []
    real = event_read_models.tile_fields

    def counting(session: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(session.id)
        return real(session, *args, **kwargs)

    monkeypatch.setattr(event_read_models, "tile_fields", counting)

    page = service.list_sessions(SessionFilter(limit=1))

    assert calls == [item.id for item in page.items]
    assert len(calls) == 1


def test_pages_session_events_when_limit_smaller_than_events(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]
    first = service.session_events("s-a", types=frozenset(), page=PageRequest(limit=5))
    second = service.session_events(
        "s-a", types=frozenset(), page=PageRequest(limit=50, cursor=first.next_cursor)
    )

    ids = [item.event_id for item in [*first.items, *second.items]]
    assert len(ids) == len(set(ids)) == first.total_estimate
    assert second.next_cursor is None


def _all_pages(service: Any, types: frozenset[EventType], limit: int) -> list[list[str]]:
    pages: list[list[str]] = []
    cursor = None
    while True:
        page = service.session_events(
            "s-a", types=types, page=PageRequest(limit=limit, cursor=cursor)
        )
        pages.append([item.event_id for item in page.items])
        cursor = page.next_cursor
        if cursor is None:
            return pages


def test_pages_unfiltered_events_like_filtered_ones_when_every_type_wanted(
    store: InMemoryEventStore,
) -> None:
    service = _service(store, NOW)[0]

    for limit in (1, 3, 7, 200):
        assert _all_pages(service, frozenset(), limit) == _all_pages(
            service, frozenset(EventType), limit
        )


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
    fold = event_read_models.fold_session_with_problems

    def counting_fold(events: Sequence[StoredEvent], **options: Any) -> FoldedSession:
        folded.append(events[0].event.session)
        return fold(events, **options)

    monkeypatch.setattr(event_read_models, "fold_session_with_problems", counting_fold)
    service = _service(store, NOW)[0]
    before = service.get_session("s-a")
    folded.clear()

    store.append([an_event(session="s-b", timestamp=NOW - timedelta(minutes=1))])
    after = service.get_session("s-a")
    changed = service.get_session("s-b")

    assert folded == ["s-b"]
    assert after == before
    assert changed.last_activity_at == NOW - timedelta(minutes=1)


def test_pages_search_without_repeats_when_session_ids_at_cap() -> None:
    store = InMemoryEventStore()
    ids = [f"{index}" + "s" * (MAX_ID_CHARS - 1) for index in range(5)]
    for index, session in enumerate(ids):
        store.append(a_session_events(session, start=SCENARIO_START + timedelta(minutes=index)))
    service = _service(store, SCENARIO_START + timedelta(hours=1))[0]

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        page = service.search_events("sss", PageRequest(limit=1, cursor=cursor))
        seen.extend(hit.href for hit in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert sorted(seen) == sorted(f"/sessions/{session}" for session in ids)
    assert len(seen) == len(set(seen))


class FoldCounter:
    """Counts the folds and canonical sorts ``FoldedEventReadModels`` runs, by wrapping them."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.runs: list[str] = []
        self.approval_folds = 0
        self.learning_folds = 0
        self.sorted_events = 0
        fold_run = event_read_models.fold_run
        fold_approvals = event_read_models.fold_approvals
        fold_learnings = event_read_models.fold_learnings
        canonical = event_read_models.canonical_events

        def counting_run(run_id: str, events: Any, **options: Any) -> Any:
            self.runs.append(run_id)
            return fold_run(run_id, events, **options)

        def counting_approvals(events: Any, **options: Any) -> Any:
            self.approval_folds += 1
            return fold_approvals(events, **options)

        def counting_learnings(events: Any) -> Any:
            self.learning_folds += 1
            return fold_learnings(events)

        def counting_canonical(events: Any) -> Any:
            materialized = events if isinstance(events, list) else list(events)
            result = canonical(materialized)
            if result is not materialized:
                self.sorted_events += len(materialized)
            return result

        monkeypatch.setattr(event_read_models, "fold_run", counting_run)
        monkeypatch.setattr(event_read_models, "fold_approvals", counting_approvals)
        monkeypatch.setattr(event_read_models, "fold_learnings", counting_learnings)
        monkeypatch.setattr(event_read_models, "canonical_events", counting_canonical)

    def reset(self) -> None:
        self.runs.clear()
        self.approval_folds = self.learning_folds = self.sorted_events = 0


def _many_runs_store() -> InMemoryEventStore:
    store = InMemoryEventStore()
    for number in range(20):
        start = SCENARIO_START + timedelta(hours=number)
        store.append(
            [
                *a_run_events(f"run{number:04d}", issue=f"DEM-{number}", start=start),
                *a_session_events(f"s-{number:02d}", start=start),
                _guard_ask(f"s-{number:02d}", 60 * number + 1),
                *learning_events(f"learning-{number}", session=f"s-{number:02d}", start=start),
            ]
        )
    return store


def test_refolds_only_the_touched_run_when_a_batch_adds_to_one_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _many_runs_store()
    counter = FoldCounter(monkeypatch)
    service = _service(store, SCENARIO_START + timedelta(days=2))[0]
    before = service.list_runs(RunFilter(limit=100))
    counter.reset()

    late = an_event(
        session="run:run0003",
        source="executor",
        type="step.start",
        step="verify",
        timestamp=SCENARIO_START + timedelta(hours=3, minutes=50),
        payload={"run": "run0003", "step": "verify", "attempt": 2},
    )
    store.append([late])
    after = service.list_runs(RunFilter(limit=100))

    assert counter.runs == ["run0003"]
    assert counter.approval_folds == 0
    assert counter.learning_folds == 0
    assert after.total_estimate == before.total_estimate == 20


def test_refolds_only_the_touched_session_approvals_when_a_batch_adds_to_one_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _many_runs_store()
    counter = FoldCounter(monkeypatch)
    service = _service(store, SCENARIO_START + timedelta(days=2))[0]
    service.list_approvals(ApprovalFilter(status="all", limit=100))
    counter.reset()

    store.append(
        [
            an_event(
                session="s-05",
                type="message",
                timestamp=SCENARIO_START + timedelta(hours=5, minutes=30),
                payload={"role": "user"},
            )
        ]
    )
    approval = service.get_approval("toolu_ask_s-05")

    assert counter.approval_folds == 1
    assert counter.runs == []
    assert counter.learning_folds == 0
    assert approval.status == "declined"
    assert service.list_approvals(ApprovalFilter(status="all", limit=100)).total_estimate == 20


def test_refolds_learnings_only_when_a_batch_holds_a_learning_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _many_runs_store()
    counter = FoldCounter(monkeypatch)
    service = _service(store, SCENARIO_START + timedelta(days=2))[0]
    service.list_learnings(LearningFilter(limit=100))
    counter.reset()

    store.append([an_event(session="s-07", timestamp=SCENARIO_START + timedelta(hours=7))])
    service.list_learnings(LearningFilter(limit=100))
    untouched = counter.learning_folds
    store.append(
        learning_events(
            "learning-new", session="s-07", start=SCENARIO_START + timedelta(hours=7, minutes=9)
        )
    )
    learnings = service.list_learnings(LearningFilter(limit=100))

    assert untouched == 0
    assert counter.learning_folds == 1
    assert learnings.total_estimate == 21


def test_sorts_only_the_touched_session_events_when_a_batch_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _many_runs_store()
    counter = FoldCounter(monkeypatch)
    service = _service(store, SCENARIO_START + timedelta(days=2))[0]
    service.list_sessions(SessionFilter())
    total = store.high_water_mark()
    counter.reset()

    store.append([an_event(session="s-11", timestamp=SCENARIO_START + timedelta(hours=11))])
    service.list_sessions(SessionFilter())
    touched = len(service.session_events("s-11", types=frozenset(), page=PageRequest()).items)

    assert counter.sorted_events == touched
    assert touched < total // 10


def test_folds_same_views_as_a_fresh_read_when_events_arrive_in_shuffled_batches(
    store: InMemoryEventStore,
) -> None:
    events = [*store.read_all(), *_many_runs_store().read_all()]
    events.append(_guard_ask("s-b", 58).model_copy(update={"session": "s-c", "source_id": "dup"}))
    growing = InMemoryEventStore()
    service = _service(growing, NOW)[0]
    order = shuffled(events, seed=7)
    for start in range(0, len(order), 37):
        growing.append(order[start : start + 37])
        service.list_runs(RunFilter(limit=200))
        service.list_approvals(ApprovalFilter(status="all", limit=200))
        service.list_learnings(LearningFilter(limit=200))
    fresh = _service(growing, NOW)[0]

    for read in (
        lambda s: s.list_sessions(SessionFilter(limit=200)),
        lambda s: s.list_runs(RunFilter(limit=200)),
        lambda s: s.list_approvals(ApprovalFilter(status="all", limit=200)),
        lambda s: s.list_learnings(LearningFilter(limit=200)),
        lambda s: s.needs_you(Scope()),
        lambda s: s.activity(PageRequest(limit=200)),
        lambda s: s.project_activity("demo"),
        lambda s: s.search_events("make", PageRequest(limit=200)),
    ):
        assert read(service) == read(fresh)
    assert service.get_approval("toolu_ask_s-b").session_id == "s-b"


def test_returns_problems_when_session_has_failures(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]

    problems = service.session_problems("s-a")

    assert problems.session_id == "s-a"
    assert [(p.kind, p.where, p.resolution) for p in problems.items] == [
        (ProblemKind.COMMAND_EXIT, "make check", Resolution.NEEDS_YOU)
    ]
    assert problems.summary[0].text == "1 problem: 1 needs you"
    assert service.get_session("s-a").problems == ProblemCounts(needs_you=1)
    assert service.session_problems("s-a") is problems
    assert [p.kind for p in service.session_problems("s-b").items] == [ProblemKind.GUARD_ASK_OPEN]
    assert service.session_problems("s-c").items == ()


def test_refolds_problems_when_store_grows(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]
    before = service.session_problems("s-a")

    store.append([an_event(session="s-a", timestamp=SCENARIO_START + timedelta(seconds=30))])
    after = service.session_problems("s-a")

    assert after is not before
    assert after == before


def _labelled_store() -> InMemoryEventStore:
    store = InMemoryEventStore()
    store.append(
        [
            *a_session_events("s-dem", ended=False, git_branch="jdoe/dem-7-login"),
            *a_session_events(
                "s-other",
                project="other",
                ended=False,
                cwd="/work/other/.claude/worktrees/oth-3-fix",
            ),
        ]
    )
    return store


def test_applies_issue_when_hub_rules_known() -> None:
    rules = {"demo": LabelRules(teams=("DEM",), branch_prefix="jdoe/")}
    service = FoldedEventReadModels(
        _labelled_store(),
        now=Clock(SCENARIO_START + timedelta(minutes=8)),
        label_rules_of=rules.get,
    )

    listed = {s.id: s for s in service.list_sessions(SessionFilter()).items}
    tiles = {tile.id: tile for tile in service.list_live_sessions(Scope()).items}
    one = service.get_session("s-dem")

    for labelled in (listed["s-dem"].label, tiles["s-dem"].label, one.label):
        assert labelled is not None
        assert labelled.issue == "DEM-7"
    assert listed["s-other"].label is not None
    assert listed["s-other"].label.issue is None
    rules["other"] = LabelRules(teams=("OTH",))
    rules["demo"] = LabelRules(teams=("XYZ",))
    again = {s.id: s for s in service.list_sessions(SessionFilter()).items}
    assert again["s-other"].label is not None
    assert again["s-other"].label.issue == "OTH-3"
    assert again["s-dem"].label is not None
    assert again["s-dem"].label.issue is None


def test_leaves_issue_empty_when_no_hub_rules() -> None:
    service = FoldedEventReadModels(
        _labelled_store(), now=Clock(SCENARIO_START + timedelta(minutes=8))
    )

    label = service.get_session("s-dem").label

    assert label is not None
    assert label.issue is None


def _linked_service(links: dict[tuple[str, str], AgentSessionLink]) -> FoldedEventReadModels:
    store = InMemoryEventStore()
    store.append(
        [
            *a_session_events("s-web", ended=False),
            *a_session_events("s-cli", ended=False),
        ]
    )
    return FoldedEventReadModels(
        store,
        now=Clock(SCENARIO_START + timedelta(minutes=8)),
        agent_session_link_of=lambda project, session_id: links.get((project, session_id)),
    )


def test_carries_agent_session_id_when_link_known_agent_session_link() -> None:
    service = _linked_service({("demo", "s-web"): AgentSessionLink(agent_session_id="a-1")})

    listed = {s.id: s for s in service.list_sessions(SessionFilter()).items}
    one = service.get_session("s-web")

    assert listed["s-web"].agent_session_id == "a-1"
    assert listed["s-cli"].agent_session_id is None
    assert one.agent_session_id == "a-1"


def test_answers_observed_by_project_when_session_known(store: InMemoryEventStore) -> None:
    service = _service(store, NOW)[0]

    assert service.is_observed("demo", "s-a")
    assert not service.is_observed("other", "s-a")
    assert not service.is_observed("demo", "s-unknown")


def test_shows_waiting_tile_when_permission_pending_agent_session_link() -> None:
    links = {("demo", "s-web"): AgentSessionLink(agent_session_id="a-1", waiting=True)}
    service = _linked_service(links)

    tiles = {tile.id: tile for tile in service.list_live_sessions(Scope()).items}
    links[("demo", "s-web")] = AgentSessionLink(agent_session_id="a-1")
    later = {tile.id: tile for tile in service.list_live_sessions(Scope()).items}

    assert (tiles["s-web"].group, tiles["s-web"].status) == ("waiting", SessionStatus.WAITING)
    assert tiles["s-web"].waiting_reason == "Permission prompt"
    assert tiles["s-cli"].group == "live"
    assert later["s-web"].group == "live"
    assert service.get_session("s-web").status == SessionStatus.LIVE


def test_carries_agent_session_id_on_tile_when_link_known_agent_session_link() -> None:
    service = _linked_service({("demo", "s-web"): AgentSessionLink(agent_session_id="a-1")})

    tiles = {tile.id: tile for tile in service.list_live_sessions(Scope()).items}

    assert tiles["s-web"].agent_session_id == "a-1"
    assert tiles["s-cli"].agent_session_id is None


def _usage_signal(
    session: str, seconds: float, payload: dict[str, object], *, project: str = "demo"
) -> Event:
    type_ = "message" if "slash_command" in payload else "tool.call"
    return an_event(
        project=project,
        session=session,
        type=type_,
        timestamp=SCENARIO_START + timedelta(seconds=seconds),
        source_id=f"{session}:usage:{seconds}",
        payload=payload,
    )


def _skill_usage_store() -> InMemoryEventStore:
    # E5: the two /feature messages and the Skill call are 6 s or more apart.
    prompt = {"role": "user", "chars": 8, "slash_command": "/feature"}
    store = InMemoryEventStore()
    store.append(
        [
            _usage_signal("s-use", 0, prompt),
            _usage_signal("s-use", 60, prompt),
            _usage_signal(
                "s-use",
                120,
                {"tool": "Skill", "tool_use_id": "toolu_skill", "skill": "hub-workflow:feature"},
            ),
            _usage_signal("s-old", -31 * 24 * 3_600, prompt),
            _usage_signal("s-oth", 30, prompt, project="other"),
            *(
                _usage_signal(
                    "s-use",
                    180 + n,
                    {"tool": "Agent", "tool_use_id": f"toolu_agent_{n}", "subagent_type": name},
                )
                for n, name in enumerate(("evaluator", "evaluator", "hub-workflow:evaluator"))
            ),
        ]
    )
    return store


def test_counts_skill_usage_when_project_events_folded() -> None:
    service, _ = _service(_skill_usage_store(), NOW)

    usage = service.skill_usage("demo")

    assert usage.since == NOW - timedelta(days=30)
    feature = usage.by_skill["feature"]
    assert (feature.count, feature.user_count, feature.model_count) == (3, 2, 1)
    assert feature.last_used_at == SCENARIO_START + timedelta(seconds=120)
    assert usage.by_agent["evaluator"].count == 3
    assert set(usage.by_skill) == {"feature"}
    assert set(usage.by_agent) == {"evaluator"}
    assert usage.model_dump(mode="json") == {
        "since": usage.model_dump(mode="json")["since"],
        "by_skill": {
            "feature": {
                "count": 3,
                "user_count": 2,
                "model_count": 1,
                "last_used_at": feature.model_dump(mode="json")["last_used_at"],
            }
        },
        "by_agent": {
            "evaluator": {
                "count": 3,
                "user_count": 0,
                "model_count": 3,
                "last_used_at": usage.by_agent["evaluator"].model_dump(mode="json")["last_used_at"],
            }
        },
        "truncated": False,
    }


def test_reuses_skill_usage_when_store_and_second_unchanged() -> None:
    service, clock = _service(_skill_usage_store(), NOW)

    first = service.skill_usage("demo")
    clock.now = NOW + timedelta(milliseconds=200)
    again = service.skill_usage("demo")
    other = service.skill_usage("other")

    assert again is first
    assert other.by_skill["feature"].count == 1
    assert service.skill_usage("nobody").by_skill == {}
