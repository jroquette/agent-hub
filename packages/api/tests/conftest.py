"""Fixtures of the api tests: settings under tmp_path, in-process clients, and the fakes the
routes are tested against (read models, hook mapper, event reader, clock)."""

import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.app import create_app
from agent_hub.api.change_feed import ChangeFeed
from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.approvals.approval import Approval
from agent_hub.core.brain.brain_note import BrainNote, BrainTree
from agent_hub.core.events.event import Event, EventType
from agent_hub.core.events.event_query import EventPage, EventQuery
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.features.feature_view import FeatureDetail, FeatureView
from agent_hub.core.features.ticket_view import FeatureTickets
from agent_hub.core.hubs.finding_view import FindingView
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.ingestion.hook_envelope import HookEnvelope
from agent_hub.core.ingestion.ingestion_ports import HookMapping
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.learnings.learning import (
    Learning,
    LearningActionResult,
    LearningDetail,
    LearningState,
)
from agent_hub.core.projects.project_views import (
    ActivityItem,
    LiveTile,
    NeedsYouItem,
    ProjectActivity,
    ProjectDetail,
    ProjectNow,
    ProjectSummary,
    RepoView,
    SearchHit,
    StreamCounts,
)
from agent_hub.core.readmodels.filters import (
    ApprovalFilter,
    LearningFilter,
    PageRequest,
    RunFilter,
    Scope,
    SessionFilter,
)
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.readmodels.settings_view import SettingsView
from agent_hub.core.runs.workflow_run import WorkflowRun
from agent_hub.core.sessions.problem import SessionProblems
from agent_hub.core.sessions.session import (
    Session,
    SessionCost,
    SessionFileChange,
    SessionSummary,
    TimelineEvent,
)
from agent_hub.core.skills.skill_view import (
    BundledFileText,
    ItemKind,
    SkillCatalog,
    SkillDetail,
    SkillUsage,
)

FIXED_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
PORT = 7420
BASE_URL = f"http://127.0.0.1:{PORT}"
# The launch token of the test apps (synthetic); their clients carry its cookie, so the
# agent-session routes are reachable as from a signed-in page.
SESSION_TOKEN = "synthetic-session-token-0123456789abcdefghijk"  # noqa: S105 -- synthetic


@pytest.fixture
def api_settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        db_path=tmp_path / "agent-hub.db",
        registry_path=tmp_path / "hubs.json",
        port=PORT,
        running_version="0.8.0",
        clock=lambda: FIXED_NOW,
        session_token=SESSION_TOKEN,
    )


@pytest.fixture
def web_dist(tmp_path: Path) -> Path:
    """A built app stand-in: an index page and one asset."""
    directory = tmp_path / "web_dist"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>agent-hub</title>", "utf-8")
    (directory / "assets" / "app.js").write_text("console.log('app')", "utf-8")
    return directory


@pytest.fixture
def client(api_settings: ApiSettings, web_dist: Path) -> Iterator[TestClient]:
    app = create_app(api_settings, web_dist=web_dist)
    with TestClient(app, base_url=BASE_URL, raise_server_exceptions=False) as test_client:
        test_client.cookies.set(cookie_name(PORT), SESSION_TOKEN)
        yield test_client


def _page[T](items: Sequence[T]) -> Page[T]:
    return Page[T](items=tuple(items), next_cursor=None, total_estimate=len(items))


def _found[T](items: dict[str, T], entity: str, entity_id: str) -> T:
    if entity_id not in items:
        raise EntityNotFoundError(entity=entity, entity_id=entity_id)
    return items[entity_id]


@dataclass
class FakeEventReadModels:
    """``EventReadModels`` over lists of built read models; records the filters it was given."""

    sessions: list[Session] = field(default_factory=list)
    runs: list[WorkflowRun] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    learnings: list[Learning] = field(default_factory=list)
    tiles: list[LiveTile] = field(default_factory=list)
    timeline: dict[str, list[TimelineEvent]] = field(default_factory=dict)
    summaries: dict[str, SessionSummary] = field(default_factory=dict)
    files: dict[str, list[SessionFileChange]] = field(default_factory=dict)
    costs: dict[str, SessionCost] = field(default_factory=dict)
    problems: dict[str, SessionProblems] = field(default_factory=dict)
    needs: list[NeedsYouItem] = field(default_factory=list)
    activity_items: list[ActivityItem] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    usages: dict[str, SkillUsage] = field(default_factory=dict)
    counts: StreamCounts = field(
        default_factory=lambda: StreamCounts(
            approvals_open=0, live_sessions=0, failed_runs_7d=0, learnings_proposed=0
        )
    )
    calls: list[tuple[str, object]] = field(default_factory=list)
    failure: Exception | None = None

    def _call(self, name: str, argument: object) -> None:
        self.calls.append((name, argument))
        if self.failure is not None:
            raise self.failure

    def list_sessions(self, session_filter: SessionFilter) -> Page[Session]:
        self._call("list_sessions", session_filter)
        return _page(self.sessions)

    def get_session(self, session_id: str) -> Session:
        self._call("get_session", session_id)
        return _found({item.id: item for item in self.sessions}, "session", session_id)

    def session_summary(self, session_id: str) -> SessionSummary:
        self._call("session_summary", session_id)
        return _found(self.summaries, "session", session_id)

    def session_events(
        self, session_id: str, *, types: frozenset[EventType], page: PageRequest
    ) -> Page[TimelineEvent]:
        self._call("session_events", (session_id, types, page))
        events = _found(self.timeline, "session", session_id)
        return _page([event for event in events if not types or event.type in types])

    def session_files(self, session_id: str) -> Page[SessionFileChange]:
        self._call("session_files", session_id)
        return _page(_found(self.files, "session", session_id))

    def session_cost(self, session_id: str) -> SessionCost:
        self._call("session_cost", session_id)
        return _found(self.costs, "session", session_id)

    def session_problems(self, session_id: str) -> SessionProblems:
        self._call("session_problems", session_id)
        return _found(self.problems, "session", session_id)

    def list_live_sessions(self, scope: Scope) -> Page[LiveTile]:
        self._call("list_live_sessions", scope)
        return _page([tile for tile in self.tiles if scope.project in {None, tile.project}])

    def list_runs(self, run_filter: RunFilter) -> Page[WorkflowRun]:
        self._call("list_runs", run_filter)
        return _page(self.runs)

    def get_run(self, run_id: str) -> WorkflowRun:
        self._call("get_run", run_id)
        return _found({item.id: item for item in self.runs}, "run", run_id)

    def list_approvals(self, approval_filter: ApprovalFilter) -> Page[Approval]:
        self._call("list_approvals", approval_filter)
        return _page(self.approvals)

    def get_approval(self, approval_id: str) -> Approval:
        self._call("get_approval", approval_id)
        return _found({item.id: item for item in self.approvals}, "approval", approval_id)

    def list_learnings(self, learning_filter: LearningFilter) -> Page[Learning]:
        self._call("list_learnings", learning_filter)
        return _page(self.learnings)

    def get_learning(self, learning_id: str) -> Learning:
        self._call("get_learning", learning_id)
        return _found({item.id: item for item in self.learnings}, "learning", learning_id)

    def project_activity(self, project: str) -> ProjectActivity:
        self._call("project_activity", project)
        return ProjectActivity(
            project=project,
            live_sessions=0,
            runs_in_flight_by_stage={},
            failed_runs_7d=0,
            cost_period=None,
            cost_previous_period=None,
            last_activity_at=None,
        )

    def needs_you(self, scope: Scope) -> Page[NeedsYouItem]:
        self._call("needs_you", scope)
        return _page(self.needs)

    def activity(self, page: PageRequest) -> Page[ActivityItem]:
        self._call("activity", page)
        return _page(self.activity_items)

    def search_events(self, query: str, page: PageRequest) -> Page[SearchHit]:
        self._call("search_events", (query, page))
        return _page(self.hits)

    def stream_counts(self) -> StreamCounts:
        self._call("stream_counts", None)
        return self.counts

    def skill_usage(self, project: str) -> SkillUsage:
        self._call("skill_usage", project)
        empty = SkillUsage(since=datetime(2026, 9, 13, tzinfo=UTC), by_skill={}, by_agent={})
        return self.usages.get(project, empty)


@dataclass
class FakeHubReadModels:
    """``HubReadModels`` over lists of built hub views; records the calls."""

    hubs: list[HubView] = field(default_factory=list)
    projects: list[ProjectSummary] = field(default_factory=list)
    details: dict[str, ProjectDetail] = field(default_factory=dict)
    nows: dict[str, ProjectNow] = field(default_factory=dict)
    repos: dict[str, list[RepoView]] = field(default_factory=dict)
    features: list[FeatureDetail] = field(default_factory=list)
    tickets: dict[str, FeatureTickets] = field(default_factory=dict)
    findings: list[FindingView] = field(default_factory=list)
    settings_view: SettingsView | None = None
    brains: dict[str, BrainTree] = field(default_factory=dict)
    notes: dict[tuple[str, str], BrainNote] = field(default_factory=dict)
    skill_catalogs: dict[str, SkillCatalog] = field(default_factory=dict)
    skill_details: dict[tuple[str, str], SkillDetail] = field(default_factory=dict)
    skill_texts: dict[tuple[str, str, str], BundledFileText] = field(default_factory=dict)
    calls: list[tuple[str, object]] = field(default_factory=list)
    failure: Exception | None = None

    def _call(self, name: str, argument: object) -> None:
        self.calls.append((name, argument))
        if self.failure is not None:
            raise self.failure

    def list_hubs(self) -> Page[HubView]:
        self._call("list_hubs", None)
        return _page(self.hubs)

    def register_hub(self, path: str) -> HubView:
        self._call("register_hub", path)
        hub = HubView.model_validate(self.hubs[0].model_dump() | {"path": path})
        self.hubs.append(hub)
        return hub

    def remove_hub(self, hub_id: str) -> None:
        self._call("remove_hub", hub_id)
        hub = _found({item.id: item for item in self.hubs}, "hub", hub_id)
        self.hubs.remove(hub)

    def list_projects(self) -> Page[ProjectSummary]:
        self._call("list_projects", None)
        return _page(self.projects)

    def get_project(self, project: str) -> ProjectDetail:
        self._call("get_project", project)
        return _found(self.details, "project", project)

    def project_now(self, project: str) -> ProjectNow:
        self._call("project_now", project)
        return _found(self.nows, "project", project)

    def project_repos(self, project: str) -> Page[RepoView]:
        self._call("project_repos", project)
        return _page(_found(self.repos, "project", project))

    def list_features(self, scope: Scope) -> Page[FeatureView]:
        self._call("list_features", scope)
        return _page([FeatureView.model_validate(_view_fields(item)) for item in self.features])

    def get_feature(self, project: str, slug: str) -> FeatureDetail:
        self._call("get_feature", (project, slug))
        by_key = {f"{item.project}/{item.slug}": item for item in self.features}
        return _found(by_key, "feature", f"{project}/{slug}")

    def feature_tickets(self, project: str, slug: str) -> FeatureTickets:
        self._call("feature_tickets", (project, slug))
        return _found(self.tickets, "feature", f"{project}/{slug}")

    def doctor_findings(self, scope: Scope) -> Page[FindingView]:
        self._call("doctor_findings", scope)
        return _page(self.findings)

    def settings(self) -> SettingsView:
        self._call("settings", None)
        if self.settings_view is None:
            raise EntityNotFoundError(entity="settings", entity_id="settings")
        return self.settings_view

    def brain_tree(self, project: str) -> BrainTree:
        self._call("brain_tree", project)
        return _found(self.brains, "project", project)

    def brain_note(self, project: str, path: str) -> BrainNote:
        self._call("brain_note", (project, path))
        if (project, path) not in self.notes:
            raise EntityNotFoundError(entity="brain note", entity_id=path)
        return self.notes[(project, path)]

    def skill_catalog(self, project: str) -> SkillCatalog:
        self._call("skill_catalog", project)
        return _found(self.skill_catalogs, "project", project)

    def skill_detail(self, project: str, *, kind: ItemKind, source: str, name: str) -> SkillDetail:
        """By ``(project, item id)``."""
        item = f"{kind}/{source}/{name}"
        self._call("skill_detail", (project, item))
        if (project, item) not in self.skill_details:
            raise EntityNotFoundError(entity="skill", entity_id=item)
        return self.skill_details[(project, item)]

    def skill_file(
        self, project: str, *, kind: ItemKind, source: str, name: str, file_id: str
    ) -> BundledFileText:
        """By ``(project, item id, file id)``."""
        item = f"{kind}/{source}/{name}"
        self._call("skill_file", (project, item, file_id))
        if (project, item, file_id) not in self.skill_texts:
            raise EntityNotFoundError(entity="skill file", entity_id=file_id)
        return self.skill_texts[(project, item, file_id)]


@dataclass
class FakeLearningReads:
    """``LearningReads`` over built learning details; records the calls."""

    details: list[LearningDetail] = field(default_factory=list)
    calls: list[tuple[str, object]] = field(default_factory=list)

    def list_learnings(self, learning_filter: LearningFilter) -> Page[Learning]:
        self.calls.append(("list_learnings", learning_filter))
        return _page([Learning.model_validate(_learning_fields(item)) for item in self.details])

    def get_learning(self, learning_id: str) -> LearningDetail:
        self.calls.append(("get_learning", learning_id))
        return _found({item.id: item for item in self.details}, "learning", learning_id)


def _learning_fields(detail: LearningDetail) -> dict[str, object]:
    return detail.model_dump(include=set(Learning.model_fields))


@dataclass
class FakeLearningDecisions:
    """``LearningDecisions`` that answers a fixed PR; records ``(action, id, target or reason)``."""

    calls: list[tuple[str, str, str]] = field(default_factory=list)
    failure: Exception | None = None

    def accept(self, learning_id: str, *, target: str) -> LearningActionResult:
        return self._decide("accept", learning_id, target, state=LearningState.ACCEPTED_PR_OPEN)

    def reject(self, learning_id: str, *, reason: str) -> LearningActionResult:
        return self._decide("reject", learning_id, reason, state=LearningState.REJECTED_PR_OPEN)

    def _decide(
        self, action: str, learning_id: str, value: str, *, state: LearningState
    ) -> LearningActionResult:
        self.calls.append((action, learning_id, value))
        if self.failure is not None:
            raise self.failure
        return LearningActionResult(
            state=state,
            pr_url="https://github.com/acme/demo-hub/pull/1",
            branch=f"demo/learning-{action}-testing-x",
        )


def _view_fields(detail: FeatureDetail) -> dict[str, object]:
    return detail.model_dump(include=set(FeatureView.model_fields))


class FakeHookMapper:
    """Maps an envelope to one ``tool.call`` event keyed by a hash of the hook input, and to the
    transcript a Stop hook names (``hook.transcript_path``)."""

    def __init__(self) -> None:
        self.envelopes: list[HookEnvelope] = []

    def map(self, envelope: HookEnvelope) -> HookMapping:
        self.envelopes.append(envelope)
        canonical = json.dumps(envelope.hook, sort_keys=True).encode()
        session = str(envelope.hook.get("session_id", "session-1"))
        name = str(envelope.hook.get("hook_event_name", "PreToolUse"))
        if name == "SubagentStart":
            return HookMapping(events=())
        event = Event(
            project=envelope.project,
            session=session,
            type=EventType.TOOL_CALL,
            timestamp=envelope.sent_at,
            source="claude_code",
            source_id=f"{session}:{name}:{hashlib.sha256(canonical).hexdigest()[:16]}",
            payload={"tool": str(envelope.hook.get("tool_name", "Bash"))},
            repo=envelope.repo,
        )
        return HookMapping(events=(event,))


def stored_event_id(seq: int) -> str:
    """A UUIDv7-shaped event id that sorts with ``seq``."""
    return str(UUID(f"01929a4e-0000-7000-8000-{seq:012x}"))


class ListEventReader:
    """``EventReader`` over a list: events get ``seq`` 1, 2, ... in the order they are added."""

    def __init__(self, *, received_at: Callable[[], datetime] = lambda: FIXED_NOW) -> None:
        self.stored: list[StoredEvent] = []
        self._received_at = received_at

    def add(self, *events: Event) -> list[StoredEvent]:
        added = []
        for event in events:
            seq = len(self.stored) + 1
            stored = StoredEvent(
                seq=seq,
                event_id=stored_event_id(seq),
                received_at=self._received_at(),
                event=event,
            )
            self.stored.append(stored)
            added.append(stored)
        return added

    def query(self, query: EventQuery) -> EventPage:
        matching = [stored for stored in self.stored if _matches(stored, query)]
        if query.order == "desc":
            matching.reverse()
        items = tuple(matching[: query.limit])
        more = len(matching) > query.limit
        return EventPage(items=items, next_after_seq=items[-1].seq if more else None)

    def find(self, event_id: str) -> StoredEvent | None:
        return next((item for item in self.stored if item.event_id == event_id), None)

    def high_water_mark(self) -> int:
        return len(self.stored)


def _matches(stored: StoredEvent, query: EventQuery) -> bool:
    event = stored.event
    checks = (
        query.project in {None, event.project},
        query.session in {None, event.session},
        not query.types or event.type in query.types,
        query.after_seq is None or stored.seq > query.after_seq,
        query.before_seq is None or stored.seq < query.before_seq,
        query.since is None or event.timestamp >= query.since,
        query.until is None or event.timestamp < query.until,
    )
    return all(checks)


class FakeClock:
    """The streams' timer: ``sleep`` returns at once and moves both clocks; ``on_sleep`` runs
    after each move (a test appends events or closes the feed there)."""

    def __init__(self, start: datetime = FIXED_NOW) -> None:
        self.start = start
        self.elapsed = 0.0
        self.on_sleep: Callable[[float], None] = lambda _: None

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.elapsed)

    def monotonic(self) -> float:
        return self.elapsed

    async def sleep(self, seconds: float) -> None:
        self.elapsed += seconds
        self.on_sleep(self.elapsed)


@dataclass
class Wired:
    """An app wired to fakes, with each fake reachable from the test."""

    client: TestClient
    events: FakeEventReadModels
    hubs: FakeHubReadModels
    reader: ListEventReader
    clock: FakeClock
    feed: ChangeFeed
    counters: IngestionCounters
    learning_reads: FakeLearningReads = field(default_factory=FakeLearningReads)
    decisions: FakeLearningDecisions = field(default_factory=FakeLearningDecisions)

    def wire(self, **ports: object) -> None:
        """Replace some of the app's ports (``learning_reads=...``) for the rest of the test."""
        state = self.client.app.state  # type: ignore[attr-defined]
        state.ports = replace(state.ports, **ports)


@pytest.fixture
def wired(api_settings: ApiSettings, web_dist: Path) -> Iterator[Wired]:
    events = FakeEventReadModels()
    hubs = FakeHubReadModels()
    reader = ListEventReader()
    clock = FakeClock()
    feed = ChangeFeed(reader, timer=clock)
    counters = IngestionCounters(clock=lambda: FIXED_NOW)
    ports = ApiPorts(
        event_read_models=events,
        hub_read_models=hubs,
        event_reader=reader,
        change_feed=feed,
        counters=counters,
    )
    app = create_app(api_settings, ports=ports, web_dist=web_dist)
    with TestClient(app, base_url=BASE_URL, raise_server_exceptions=False) as test_client:
        test_client.cookies.set(cookie_name(PORT), SESSION_TOKEN)
        yield Wired(test_client, events, hubs, reader, clock, feed, counters)


@pytest.fixture
def fakes() -> SimpleNamespace:
    """The fakes' classes, for tests that build their own (test modules cannot import here)."""
    return SimpleNamespace(
        EventReadModels=FakeEventReadModels,
        HubReadModels=FakeHubReadModels,
        HookMapper=FakeHookMapper,
        EventReader=ListEventReader,
        Clock=FakeClock,
        event_id=stored_event_id,
    )


type ClientOpener = Callable[..., AbstractContextManager[TestClient]]


@pytest.fixture
def open_client(api_settings: ApiSettings, web_dist: Path) -> ClientOpener:
    """Opens a client on an app built with the given ``create_app`` keywords."""

    @contextmanager
    def opened(**options: Any) -> Iterator[TestClient]:
        app = create_app(api_settings, web_dist=web_dist, **options)
        with TestClient(app, base_url=BASE_URL, raise_server_exceptions=False) as test_client:
            yield test_client

    return opened
