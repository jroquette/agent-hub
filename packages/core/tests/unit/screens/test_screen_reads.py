"""The screen reads (ADR 0056) over counting fakes of the read ports.

The shell read: ``hub_count`` from ``list_hubs``; every project of ``list_projects`` in its order,
whatever the scope; the features of the scope that need you, counted over a fresh
``list_live_sessions(scope)`` (or no tile when the store cannot read them) and a feature list kept
per scope for 30 s (the Features list's own refresh), for at most 8 scopes, which
``forget_features()`` drops; ``has_workflow_runs`` from one workflow run of any project. The clock
is the read's ``monotonic`` keyword, moved by the test.

The portfolio read (Home): every project of ``list_projects`` whatever the scope, what
``needs_you`` answers for the scope, and the scope's first ``activity`` page of 20 items
(Home's activity page), each as the read port answers it.

The project overview read: each resource part as its read port answers it for the project (the
runs' first 200, of any kind; every card), and the project's 200 newest sessions narrowed to
those of issues (``label.issue``, else ``issue``, upper case) with a session active in the last 7
days, newest first; ``has_sessions`` says whether those 200 held any. "Now" is the real clock,
so each session's age is set hours or days away from the 7-day edge.

The sessions read (the inbox): each status section's first page of 50 for the scope and sort,
the period's ``from`` bounding Finished only; every project's card; every project's features;
and, only for a request allowed to read them, the agent sessions of the scope and the driver's
capabilities, the latter only when they answer within the read's wait (a probe of ``claude`` is
left running, shared by the reads that overlap it, and its answer taken by the next read).

The session detail read: the session, its first page of 1,000 events of every type, its summary
only once it has ended, its problems only when it counts one (whatever its status), its
project's features, and the driver's capabilities, each as its read port answers it.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from operator import attrgetter
from typing import Any

import pytest

from agent_hub.core.agent_sessions.agent_session import (
    AgentSession,
    AgentSessionList,
    AgentSessionStatus,
)
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.errors import AgentHubError
from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.features.feature_view import FeatureView
from agent_hub.core.hub_config.config_view import HubConfigView
from agent_hub.core.hubs.finding_view import DoctorFindings, FindingView
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.projects.project_views import (
    ActivityItem,
    LiveTile,
    NeedsYouItem,
    NowItem,
    ProjectDetail,
    ProjectNow,
    ProjectSummary,
    RepoView,
    TrackerView,
)
from agent_hub.core.readmodels.filters import PageRequest, RunFilter, Scope, SessionFilter
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.runs.workflow_run import IssueRef, RunStep, WorkflowRun
from agent_hub.core.screens.screen_reads import ScreenReads
from agent_hub.core.screens.screen_views import (
    PortfolioView,
    SessionDetailView,
    ShellProject,
    ShellView,
)
from agent_hub.core.sessions.problem import Resolution, SessionProblems
from agent_hub.core.sessions.session import (
    Actor,
    Outcome,
    ProblemCounts,
    Session,
    SessionSegment,
    SessionStatus,
    SessionSummary,
    SummaryLine,
    TimelineEvent,
)
from agent_hub.core.testing.discovery_fakes import a_demo_config_view
from agent_hub.core.testing.read_model_builders import (
    EVENT_ID,
    HUB_ID,
    a_feature_view,
    a_finding_view,
    a_hub_view,
    a_problem,
    a_project_summary,
    a_run,
    a_session,
    a_session_label,
    a_session_problems,
    an_agent_session,
)

AT = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
START = 1_000.0


def _page[T](items: Sequence[T]) -> Page[T]:
    return Page[T](items=tuple(items), next_cursor=None, total_estimate=len(items))


@dataclass
class CountingEvents:
    """The event reads the screen reads make, over lists, filtered and cut to a page as the
    read models do; records each call. A session's events page names, as its next cursor, how
    many events came before the next page. The live tiles and the runs raise the error
    ``failures`` holds for them, once the call is recorded."""

    tiles: list[LiveTile] = field(default_factory=list)
    runs: list[WorkflowRun] = field(default_factory=list)
    needs: list[NeedsYouItem] = field(default_factory=list)
    feed: list[ActivityItem] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    timeline: dict[str, list[TimelineEvent]] = field(default_factory=dict)
    summaries: dict[str, SessionSummary] = field(default_factory=dict)
    problems: dict[str, SessionProblems] = field(default_factory=dict)
    failures: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, object]] = field(default_factory=list)

    def get_session(self, session_id: str) -> Session:
        self.calls.append(("get_session", session_id))
        return _session_of({item.id: item for item in self.sessions}, session_id)

    def session_summary(self, session_id: str) -> SessionSummary:
        self.calls.append(("session_summary", session_id))
        return _session_of(self.summaries, session_id)

    def session_events(
        self, session_id: str, *, types: frozenset[EventType], page: PageRequest
    ) -> Page[TimelineEvent]:
        self.calls.append(("session_events", (session_id, types, page)))
        kept = [
            event
            for event in _session_of(self.timeline, session_id)
            if not types or event.type in types
        ]
        more = len(kept) > page.limit
        return Page[TimelineEvent](
            items=tuple(kept[: page.limit]),
            next_cursor=str(page.limit) if more else None,
            total_estimate=len(kept),
        )

    def session_problems(self, session_id: str) -> SessionProblems:
        self.calls.append(("session_problems", session_id))
        return _session_of(self.problems, session_id)

    def list_live_sessions(self, scope: Scope) -> Page[LiveTile]:
        self.calls.append(("list_live_sessions", scope))
        if "list_live_sessions" in self.failures:
            raise self.failures["list_live_sessions"]
        return _page([tile for tile in self.tiles if scope.project in {None, tile.project}])

    def list_runs(self, run_filter: RunFilter) -> Page[WorkflowRun]:
        self.calls.append(("list_runs", run_filter))
        if "list_runs" in self.failures:
            raise self.failures["list_runs"]
        kept = [
            run
            for run in self.runs
            if run_filter.project in {None, run.project} and run_filter.kind in {None, run.kind}
        ]
        return _page(kept[: run_filter.limit])

    def needs_you(self, scope: Scope) -> Page[NeedsYouItem]:
        self.calls.append(("needs_you", scope))
        return _page([item for item in self.needs if scope.project in {None, item.project}])

    def activity(self, page: PageRequest) -> Page[ActivityItem]:
        self.calls.append(("activity", page))
        kept = [item for item in self.feed if page.project in {None, item.project}]
        return _page(kept[: page.limit])

    def list_sessions(self, session_filter: SessionFilter) -> Page[Session]:
        self.calls.append(("list_sessions", session_filter))
        since = session_filter.started_from
        kept = [
            item
            for item in self.sessions
            if session_filter.project in {None, item.project}
            and session_filter.status in {None, item.status}
            and (since is None or item.started_at >= since)
        ]
        sort = session_filter.sort
        kept.sort(key=attrgetter(sort.removeprefix("-")), reverse=sort.startswith("-"))
        return _page(kept[: session_filter.limit])


@dataclass
class CountingHubs:
    """The hub reads the screen reads make, over lists and per-project entries; records each
    call. ``during_listing``, when set, is called once from inside the next feature listing."""

    hubs: list[HubView] = field(default_factory=list)
    projects: list[ProjectSummary] = field(default_factory=list)
    features: list[FeatureView] = field(default_factory=list)
    details: dict[str, ProjectDetail] = field(default_factory=dict)
    nows: dict[str, ProjectNow] = field(default_factory=dict)
    repos: dict[str, list[RepoView]] = field(default_factory=dict)
    configs: dict[str, HubConfigView] = field(default_factory=dict)
    findings: list[FindingView] = field(default_factory=list)
    during_listing: Callable[[], None] | None = None
    calls: list[tuple[str, object]] = field(default_factory=list)

    def list_hubs(self) -> Page[HubView]:
        self.calls.append(("list_hubs", None))
        return _page(self.hubs)

    def list_projects(self) -> Page[ProjectSummary]:
        self.calls.append(("list_projects", None))
        return _page(self.projects)

    def list_features(self, scope: Scope) -> Page[FeatureView]:
        self.calls.append(("list_features", scope))
        if self.during_listing is not None:
            landed, self.during_listing = self.during_listing, None
            landed()
        return _page([item for item in self.features if scope.project in {None, item.project}])

    def get_project(self, project: str) -> ProjectDetail:
        self.calls.append(("get_project", project))
        return _of(self.details, project)

    def project_now(self, project: str) -> ProjectNow:
        self.calls.append(("project_now", project))
        return _of(self.nows, project)

    def project_repos(self, project: str) -> Page[RepoView]:
        self.calls.append(("project_repos", project))
        return _page(_of(self.repos, project))

    def hub_config(self, project: str) -> HubConfigView:
        self.calls.append(("hub_config", project))
        return _of(self.configs, project)

    def doctor_findings(self, scope: Scope) -> DoctorFindings:
        self.calls.append(("doctor_findings", scope))
        return _findings([item for item in self.findings if scope.project in {None, item.project}])


def _of[T](entries: dict[str, T], project: str) -> T:
    """The project's entry; a project with none is unknown, as the read models answer it."""
    if project not in entries:
        raise EntityNotFoundError(entity="project", entity_id=project)
    return entries[project]


def _session_of[T](entries: dict[str, T], session: str) -> T:
    """The session's entry; a session with none is unknown, as the read models answer it."""
    if session not in entries:
        raise EntityNotFoundError(entity="session", entity_id=session)
    return entries[session]


def _findings(items: Sequence[FindingView]) -> DoctorFindings:
    return DoctorFindings(
        items=tuple(items), next_cursor=None, total_estimate=len(items), checked_at=AT
    )


class SteppedClock:
    """A monotonic clock the test sets."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now


def _count(calls: list[tuple[str, object]], name: str) -> int:
    return sum(1 for called, _argument in calls if called == name)


def a_tile(issue: str, group: str) -> LiveTile:
    """A main-session tile of project ``demo`` whose label names ``issue``."""
    fields: dict[str, object] = {
        "id": f"session-{issue}",
        "project": "demo",
        "repo": "demo-api",
        "agent": "main",
        "status": "live",
        "group": group,
        "last_action": None,
        "last_tool": None,
        "last_activity_at": AT,
        "started_at": AT,
        "turns": 1,
        "tokens_total": 10,
        "files_touched": 0,
        "errors": 0,
        "guard_denials": 0,
        "cost_usd": None,
        "label": a_session_label(issue=issue),
    }
    return LiveTile.model_validate(fields)


def _world(runs: Sequence[WorkflowRun] | None = None) -> tuple[CountingEvents, CountingHubs]:
    """Three registered hubs (one invalid), two projects listed ``other`` first, and four
    features: in ``demo`` a NO-SHIP, one a session waits on and one a session works on; in
    ``other`` one with a problem. ``demo`` has one workflow run unless ``runs`` is given."""
    hubs = CountingHubs(
        hubs=[
            a_hub_view(id="hub-other", path="/home/demo/other-hub", project="other"),
            a_hub_view(),
            a_hub_view(id="hub-broken", path="/home/demo/broken-hub", project=None, valid=False),
        ],
        projects=[
            a_project_summary(name="other", hub_id="hub-other", live_sessions=0),
            a_project_summary(name="demo", live_sessions=2),
        ],
        features=[
            a_feature_view(slug="refused", issues=(), verdict="NO-SHIP"),
            a_feature_view(slug="asked", issues=("AGH-2",)),
            a_feature_view(slug="plain", issues=("AGH-1",)),
            a_feature_view(project="other", slug="broken", issues=(), problem="unreadable"),
        ],
    )
    events = CountingEvents(
        tiles=[a_tile("AGH-2", "waiting"), a_tile("AGH-1", "live")],
        runs=[a_run()] if runs is None else list(runs),
    )
    return events, hubs


SWITCHER = (
    ShellProject(name="other", live_sessions=0),
    ShellProject(name="demo", live_sessions=2),
)


def test_composes_shell_from_hubs_projects_features_and_runs_when_read() -> None:
    events, hubs = _world()
    assert (len(hubs.hubs), len(hubs.projects), len(hubs.features)) == (3, 2, 4)

    view = ScreenReads(events, hubs, monotonic=SteppedClock()).shell(None)

    assert view == ShellView(
        hub_count=3, projects=SWITCHER, features_needing_you=3, has_workflow_runs=True
    )


def test_counts_scoped_features_when_project_given() -> None:
    events, hubs = _world()
    reads = ScreenReads(events, hubs, monotonic=SteppedClock())

    scoped = reads.shell("demo")
    everywhere = reads.shell(None)

    assert scoped == ShellView(
        hub_count=3, projects=SWITCHER, features_needing_you=2, has_workflow_runs=True
    )
    assert everywhere.features_needing_you == 3


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([a_run(project="other")], True),
        ([a_run(project="other", workflow="scenario:checkout")], False),
        ([], False),
    ],
    ids=["workflow-run-of-other-project", "scenario-run-only", "no-run"],
)
def test_finds_workflow_runs_of_any_project_when_scope_is_set(
    runs: list[WorkflowRun], *, expected: bool
) -> None:
    events, hubs = _world(runs)

    view = ScreenReads(events, hubs, monotonic=SteppedClock()).shell("demo")

    assert view.has_workflow_runs is expected


def test_keeps_feature_list_for_its_freshness_when_shell_read_again() -> None:
    events, hubs = _world()
    clock = SteppedClock()
    reads = ScreenReads(events, hubs, monotonic=clock)
    listed = []

    for elapsed in (0, 5, 29, 31):
        clock.now = START + elapsed
        reads.shell(None)
        listed.append(
            (_count(hubs.calls, "list_features"), _count(events.calls, "list_live_sessions"))
        )

    assert listed == [(1, 1), (1, 2), (1, 3), (2, 4)]


def test_lists_features_again_when_features_forgotten() -> None:
    events, hubs = _world()
    clock = SteppedClock()
    reads = ScreenReads(events, hubs, monotonic=clock)
    reads.shell(None)
    reads.shell("demo")
    assert _count(hubs.calls, "list_features") == 2

    clock.now = START + 5
    reads.forget_features()
    reads.shell(None)
    reads.shell("demo")

    assert _count(hubs.calls, "list_features") == 4


# A feature record written while the shell lists the features: that listing may be older than the
# write, so it is not kept and the next read lists again; the listing after it is kept.
def test_lists_features_again_when_forgotten_while_listing() -> None:
    events, hubs = _world()
    clock = SteppedClock()
    reads = ScreenReads(events, hubs, monotonic=clock)
    hubs.during_listing = reads.forget_features
    listed = []

    for elapsed in (0, 5, 10):
        clock.now = START + elapsed
        reads.shell(None)
        listed.append(_count(hubs.calls, "list_features"))

    assert hubs.during_listing is None
    assert listed == [1, 2, 2]


# The plan's bound on the kept lists (any ?project= value is a scope): at most 8 scopes.
SCOPES_KEPT = 8


# Within the bound the first scope read is still kept; one scope more drops it, so its next read
# lists it again. The clock does not move.
@pytest.mark.parametrize(
    ("scopes_read", "listed_again"),
    [(SCOPES_KEPT, False), (SCOPES_KEPT + 1, True)],
    ids=["as-many-as-kept", "one-more-than-kept"],
)
def test_keeps_at_most_eight_scope_lists_when_many_scopes_read(
    scopes_read: int, *, listed_again: bool
) -> None:
    events, hubs = _world()
    scopes = [f"project-{number}" for number in range(scopes_read)]
    hubs.features += [a_feature_view(project=scope, slug="plain", issues=()) for scope in scopes]
    reads = ScreenReads(events, hubs, monotonic=SteppedClock())
    for scope in scopes:
        reads.shell(scope)
    assert _count(hubs.calls, "list_features") == scopes_read

    reads.shell(scopes[0])

    assert _count(hubs.calls, "list_features") == scopes_read + int(listed_again)


# The scope's own live tiles, as the Features list read them (useLiveSessions(project)): a tile of
# other waiting on AGH-1, the issue of demo's plain feature, is not read for demo; All projects
# reads every project's tiles, where it counts.
@pytest.mark.parametrize(
    ("scope", "expected"), [("demo", 2), (None, 4)], ids=["one-project", "all-projects"]
)
def test_counts_scope_tiles_only_when_another_project_waits_on_same_issue(
    scope: str | None, expected: int
) -> None:
    events, hubs = _world()
    elsewhere = a_tile("AGH-1", "waiting").model_copy(
        update={"project": "other", "id": "session-other-AGH-1"}
    )
    events.tiles.append(elsewhere)
    assert [(tile.project, tile.group) for tile in events.tiles] == [
        ("demo", "waiting"),
        ("demo", "live"),
        ("other", "waiting"),
    ]

    view = ScreenReads(events, hubs, monotonic=SteppedClock()).shell(scope)

    assert view.features_needing_you == expected


# AC-374.7: the badge count still comes when the store cannot read the live sessions. It is then
# counted with no tile, as the Features list counted it (its tiles default to none): in All
# projects the NO-SHIP and the broken record, not the feature a session waits on.
def test_counts_features_without_tiles_when_live_sessions_unreadable() -> None:
    events, hubs = _world()
    events.failures["list_live_sessions"] = AgentHubError("the event database could not be read")

    view = ScreenReads(events, hubs, monotonic=SteppedClock()).shell(None)

    assert view == ShellView(
        hub_count=3, projects=SWITCHER, features_needing_you=2, has_workflow_runs=True
    )
    assert _count(events.calls, "list_live_sessions") == 1


# Only the live tiles may go unread: the store failing another part, or the live tiles failing
# for another reason than the store, still fails the read.
@pytest.mark.parametrize(
    ("read", "failure"),
    [
        ("list_runs", AgentHubError("the event database could not be read")),
        ("list_live_sessions", RuntimeError("the tiles could not be folded")),
    ],
    ids=["runs-unreadable", "live-sessions-fail-otherwise"],
)
def test_fails_shell_read_when_failure_is_not_unreadable_live_sessions(
    read: str, failure: Exception
) -> None:
    events, hubs = _world()
    events.failures[read] = failure

    with pytest.raises(type(failure)) as raised:
        ScreenReads(events, hubs, monotonic=SteppedClock()).shell(None)

    assert raised.value is failure


def _no_hub() -> tuple[CountingEvents, CountingHubs]:
    """No hub registered, so no project and no feature; the event log still has live tiles."""
    events, _hubs = _world()
    return events, CountingHubs()


# A scope with no feature folder, and the first run with no hub (whose answer the first-run gate
# waits on), read no live tile.
@pytest.mark.parametrize(
    ("world", "scope"),
    [(_world, "nobody"), (_no_hub, None)],
    ids=["scope-without-features", "no-hub"],
)
def test_reads_no_live_sessions_when_no_feature_listed(world: Any, scope: str | None) -> None:
    events, hubs = world()
    assert len(events.tiles) == 2
    assert [item for item in hubs.features if scope in {None, item.project}] == []

    view = ScreenReads(events, hubs, monotonic=SteppedClock()).shell(scope)

    assert view.features_needing_you == 0
    assert _count(events.calls, "list_live_sessions") == 0


def a_need(project: str, verb: str) -> NeedsYouItem:
    """A Needs you line of ``project``."""
    return NeedsYouItem(
        kind="learning", verb=verb, context="brain/_inbox", project=project, since=AT, href="/"
    )


def an_activity(project: str, minutes_ago: int) -> ActivityItem:
    """An activity item of ``project``, ``minutes_ago`` before ``AT``."""
    return ActivityItem(
        kind="learning",
        text=f"Learning proposed {minutes_ago} min ago",
        project=project,
        at=AT - timedelta(minutes=minutes_ago),
        href=None,
    )


def _portfolio_world() -> tuple[CountingEvents, CountingHubs]:
    """The shell's world, plus three Needs you lines (``other``'s first) and an activity feed
    newest first: two items of ``other``, then 25 of ``demo``."""
    events, hubs = _world()
    events.needs = [
        a_need("other", "Fix the doctor error"),
        a_need("demo", "Triage 2 learnings"),
        a_need("demo", "Approve the plan"),
    ]
    events.feed = [an_activity("other", minutes) for minutes in range(2)] + [
        an_activity("demo", minutes) for minutes in range(2, 27)
    ]
    return events, hubs


# Every project whatever the scope (the cards); the scope's Needs you lines and its 20 newest
# activity items (Home's first activity page): All projects 2 of other's and 18 of demo's.
@pytest.mark.parametrize(
    ("scope", "needs", "feed"),
    [(None, slice(0, 3), slice(0, 20)), ("demo", slice(1, 3), slice(2, 22))],
    ids=["all-projects", "one-project"],
)
def test_composes_portfolio_from_projects_needs_and_activity_when_read(
    scope: str | None, needs: slice, feed: slice
) -> None:
    events, hubs = _portfolio_world()
    assert (len(hubs.projects), len(events.needs), len(events.feed)) == (2, 3, 27)

    view = ScreenReads(events, hubs, monotonic=SteppedClock()).portfolio(scope)

    assert view == PortfolioView(
        projects=_page(hubs.projects),
        needs_you=_page(events.needs[needs]),
        activity=_page(events.feed[feed]),
    )


def a_project_detail() -> ProjectDetail:
    """The overview header of project ``demo``."""
    return ProjectDetail(
        name="demo",
        hub_id=HUB_ID,
        hub_path="/home/demo/demo-hub",
        hub_repo="acme/demo-hub",
        tracker=TrackerView(kind="linear", teams=("DEM",), ready_label=None, failed_label=None),
        default_branch="main",
        branch_prefix="jdoe/",
        platform_version="0.8.0",
        lock_version="0.8.0",
        lock_state="in_sync",
        checked_at=AT,
        modules=("cloud",),
    )


def a_repo(name: str) -> RepoView:
    """A repo of project ``demo``."""
    return RepoView(
        name=name,
        dir=name,
        github=f"acme/{name}",
        role="app",
        default_branch="main",
        check_fast="make check-fast",
        check="make check",
        agents_md_present=True,
        agents_md_lines=40,
    )


def _overview_world(sessions: Sequence[Session]) -> tuple[CountingEvents, CountingHubs]:
    """The shell's world, plus what ``demo``'s overview reads: its header, now.md, two repos and
    its config; a finding and a Needs you line of ``other``, then of ``demo``; 201 runs of
    ``demo``, newest first and the newest a scenario run, then one of ``other``; and
    ``sessions``."""
    events, hubs = _world(
        [a_run(id="00000000", workflow="scenario:checkout")]
        + [a_run(id=f"{number:08x}") for number in range(1, 201)]
        + [a_run(id="0000ffff", project="other")]
    )
    hubs.details = {"demo": a_project_detail()}
    focus = (NowItem(text="Ship the overview read"),)
    hubs.nows = {
        "demo": ProjectNow(
            project="demo", focus=focus, next=(), watch=(), source_path="brain/now.md"
        )
    }
    hubs.repos = {"demo": [a_repo("demo-api"), a_repo("demo-web")]}
    hubs.configs = {"demo": a_demo_config_view()}
    hubs.findings = [a_finding_view(project="other"), a_finding_view()]
    events.needs = [a_need("other", "Fix the doctor error"), a_need("demo", "Approve the plan")]
    events.sessions = list(sessions)
    return events, hubs


def a_session_ago(session: str, now: datetime, days: float, **overrides: object) -> Session:
    """A session of ``demo`` last active ``days`` before ``now``, started an hour before that."""
    last = now - timedelta(days=days)
    fields: dict[str, object] = {
        "id": session,
        "started_at": last - timedelta(hours=1),
        "last_activity_at": last,
    }
    return a_session(**(fields | overrides))


def _demo_sessions(now: datetime) -> list[Session]:
    """``demo``'s sessions and one of ``other``: DEM-1 this week (in a session started 30 days
    ago) and 20 days ago; DEM-3 this week, in a session with no label whose own issue is in
    lower case, and 15 days ago; DEM-2 10 days ago only, though ``other`` works on it this week;
    and one of this week on no issue."""
    return [
        a_session_ago(
            "dem-1-week",
            now,
            0.05,
            label=a_session_label(issue="DEM-1"),
            started_at=now - timedelta(days=30),
        ),
        a_session_ago("no-issue-week", now, 0.1, label=a_session_label(issue=None)),
        a_session_ago("dem-3-week", now, 2, issue="dem-3"),
        a_session_ago("dem-2-older", now, 10, label=a_session_label(issue="DEM-2")),
        a_session_ago("dem-3-older", now, 15, label=a_session_label(issue="DEM-3")),
        a_session_ago("dem-1-older", now, 20, label=a_session_label(issue="DEM-1")),
        a_session_ago(
            "other-week", now, 0.05, project="other", label=a_session_label(issue="DEM-2")
        ),
    ]


# Each resource part as its read port answers it for demo: the header, demo's findings and Needs
# you line, every card, demo's first 200 runs of any kind, now.md, its features, repos and config.
# The recent sessions are demo's of the issues worked on in the week (DEM-1; DEM-3, read from a
# session with no label), newest first, each kept whether or not it was itself active this week.
@pytest.mark.parametrize(
    ("kept", "recent", "has_sessions"),
    [
        (None, ["dem-1-week", "dem-3-week", "dem-3-older", "dem-1-older"], True),
        ({"dem-2-older", "dem-3-older"}, [], True),
        (set(), [], False),
    ],
    ids=["worked-on-this-week", "only-older-sessions", "no-session"],
)
def test_composes_project_overview_from_its_resources_when_read(
    kept: set[str] | None, recent: list[str], *, has_sessions: bool
) -> None:
    sessions = [
        item
        for item in _demo_sessions(datetime.now(UTC))
        if kept is None or item.id in kept or item.project == "other"
    ]
    events, hubs = _overview_world(sessions)
    assert (len(events.runs), events.runs[200].project, events.runs[201].project) == (
        202,
        "demo",
        "other",
    )

    view = ScreenReads(events, hubs, monotonic=SteppedClock()).project_overview("demo")

    by_id = {item.id: item for item in sessions}
    assert view.recent_sessions.items == tuple(by_id[session] for session in recent)
    assert view.has_sessions is has_sessions
    assert (view.project, view.findings, view.projects, view.needs_you, view.runs) == (
        hubs.details["demo"],
        _findings(hubs.findings[1:]),
        _page(hubs.projects),
        _page(events.needs[1:]),
        _page(events.runs[:200]),
    )
    assert (view.now, view.features, view.repos, view.config) == (
        hubs.nows["demo"],
        _page(hubs.features[:3]),
        _page(hubs.repos["demo"]),
        hubs.configs["demo"],
    )


WEEK_TOOLS = (
    "Read",
    "Edit",
    "Write",
    "Bash",
    "Grep",
    "Glob",
    "Agent",
    "Skill",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
)
RUN_STEPS = ("pick", "implement", "verify", "review", "pr")


def a_real_shaped_session(number: int, now: datetime) -> Session:
    """Session ``number`` of 200 in the week, on one of 50 issues, shaped as a real one: a label
    with a title, a branch and three workflows; three actors; eleven tool counts; two segments."""
    issue = f"DEM-{number % 50 + 1}"
    last = now - timedelta(minutes=25 * number + 5)
    started = last - timedelta(hours=2)
    return a_session(
        id=f"week-{number:03d}",
        started_at=started,
        last_activity_at=last,
        label=a_session_label(
            issue=issue,
            title=f"Export the {issue} report as CSV",
            branch=f"jdoe/{issue.lower()}-export-report",
            workflows=("/feature", "/create-plan", "/fix"),
        ),
        actors=(
            Actor(kind="main"),
            Actor(
                kind="subagent",
                type="Explore",
                agent_id=f"agent-{number}-1",
                description="Map the collector",
                started_by_event_id=EVENT_ID,
            ),
            Actor(
                kind="subagent",
                type="general-purpose",
                agent_id=f"agent-{number}-2",
                description="Check the migrations",
                started_by_event_id=EVENT_ID,
            ),
        ),
        tool_counts={tool: number % 9 + 1 for tool in WEEK_TOOLS},
        segments=(
            SessionSegment(
                index=1,
                started_at=started,
                ended_at=started + timedelta(minutes=50),
                end_reason="clear",
            ),
            SessionSegment(
                index=2, started_at=started + timedelta(hours=1), ended_at=None, end_reason=None
            ),
        ),
    )


def a_real_shaped_run(number: int, now: datetime) -> WorkflowRun:
    """Run ``number`` of 200: five steps, each with its session."""
    started = now - timedelta(hours=number + 2)
    return a_run(
        id=f"{number:08x}",
        issue=IssueRef(key=f"DEM-{number + 1}", title=f"Export the DEM-{number + 1} report"),
        steps=tuple(
            RunStep(
                key=key,
                attempt=1,
                max_attempts=1,
                status="ok",
                started_at=started + timedelta(minutes=10 * index),
                ended_at=started + timedelta(minutes=10 * index + 9),
                session_ids=(f"week-{number:03d}",),
            )
            for index, key in enumerate(RUN_STEPS)
        ),
    )


# A11: on real-shaped data (200 sessions of the week on 50 issues, 60 features, 500 findings, 200
# runs) the overview read stays under 1.5 MB (1,000,000 bytes a MB, as api_kb counts). A 201st,
# older session of a week's issue is past the 200 newest, so it stays out.
def test_bounds_overview_bytes_when_project_is_real_shaped() -> None:
    now = datetime.now(UTC)
    week = [a_real_shaped_session(number, now) for number in range(200)]
    older = a_session_ago("older", now, 9, label=a_session_label(issue="DEM-1"))
    events, hubs = _overview_world([*week, older])
    events.runs = [a_real_shaped_run(number, now) for number in range(200)]
    hubs.features = [
        a_feature_view(slug=f"feature-{number:02d}", issues=(f"DEM-{number + 1}",))
        for number in range(60)
    ]
    hubs.findings = [
        a_finding_view(
            path=f"brain/notes/note-{number:03d}.md",
            line=number + 1,
            message=f"note-{number:03d}.md links to a missing note",
        )
        for number in range(500)
    ]
    assert {(len(item.actors), len(item.tool_counts), len(item.segments)) for item in week} == {
        (3, 11, 2)
    }
    assert ({len(run.steps) for run in events.runs}, len({item.label.issue for item in week})) == (
        {5},
        50,
    )

    view = ScreenReads(events, hubs, monotonic=SteppedClock()).project_overview("demo")

    assert {item.id for item in view.recent_sessions.items} == {item.id for item in week}
    assert (len(view.runs.items), len(view.features.items), len(view.findings.items)) == (
        200,
        60,
        500,
    )
    assert len(view.model_dump_json().encode()) < 1_500_000


CAPABILITIES = DriverCapabilities(available=True, engine="in-memory", cli_version="2.1.0")
# How long the reads that expect the driver's capabilities wait for them here. The counting
# driver answers at once, but the default 50 ms is wall-clock time, which a loaded runner can
# spend on the read's other parts before the event loop takes that answer.
CAPABILITIES_WAIT = 10.0


@dataclass
class CountingAgentSessions:
    """The agent-session reads the sessions read makes: the sessions as ``GET /agent-sessions``
    filters them, and the driver's capabilities, which wait for ``release`` when it is set and
    raise ``failure`` when it is set; records each call and counts the answered probes."""

    sessions: list[AgentSession] = field(default_factory=list)
    release: asyncio.Event | None = None
    failure: Exception | None = None
    answered: int = 0
    calls: list[tuple[str, object]] = field(default_factory=list)

    async def list_sessions(
        self,
        *,
        project: str | None,
        status: AgentSessionStatus | None,
        wrote: str | None = None,
    ) -> AgentSessionList:
        self.calls.append(("list_sessions", (project, status, wrote)))
        return AgentSessionList(
            items=tuple(
                item
                for item in self.sessions
                if project in {None, item.project} and status in {None, item.status}
            )
        )

    async def capabilities(self) -> DriverCapabilities:
        self.calls.append(("capabilities", None))
        if self.failure is not None:
            raise self.failure
        if self.release is not None:
            await self.release.wait()
        self.answered += 1
        return CAPABILITIES


def an_inbox_session(
    session: str, status: SessionStatus, started_ago: timedelta, **overrides: object
) -> Session:
    """A session of ``demo`` in ``status``, started ``started_ago`` before ``AT`` and last active
    a minute later (when it ended, if it did)."""
    started = AT - started_ago
    last = started + timedelta(minutes=1)
    fields: dict[str, object] = {
        "id": session,
        "status": status,
        "started_at": started,
        "last_activity_at": last,
    }
    if status == SessionStatus.ENDED:
        fields |= {"ended_at": last, "outcome": Outcome.DONE, "end_reason": "prompt_input_exit"}
    return a_session(**(fields | overrides))


SECTIONS = ("waiting", "live", "idle", "ended")
# The period the inbox asks Finished for, a week before AT.
PERIOD_FROM = AT - timedelta(days=7)
# 51 waiting sessions of demo, each started an hour before the previous: one more than a page.
WAITING = [f"waiting-{number:02d}" for number in range(51)]


def _inbox_world() -> tuple[CountingEvents, CountingHubs, CountingAgentSessions]:
    """The shell's world (two projects, four features: three of ``demo``, one of ``other``),
    plus sessions in every section: the 51 waiting; a live one in each project; an idle one of
    ``demo`` started before the period; in Finished one of ``demo`` in the period, one before
    it and one of ``other``. The agent sessions: an idle and a running one of ``demo``, an idle
    one of ``other``."""
    events, hubs = _world()
    events.sessions = [
        *(
            an_inbox_session(session, SessionStatus.WAITING, timedelta(hours=number + 1))
            for number, session in enumerate(WAITING)
        ),
        an_inbox_session("live-demo", SessionStatus.LIVE, timedelta(hours=1)),
        an_inbox_session("live-other", SessionStatus.LIVE, timedelta(minutes=30), project="other"),
        an_inbox_session("idle-before-period", SessionStatus.IDLE, timedelta(days=30)),
        an_inbox_session("ended-in-period", SessionStatus.ENDED, timedelta(days=2)),
        an_inbox_session("ended-before-period", SessionStatus.ENDED, timedelta(days=20)),
        an_inbox_session("ended-other", SessionStatus.ENDED, timedelta(days=1), project="other"),
    ]
    agents = CountingAgentSessions(
        sessions=[
            an_agent_session(id="agent-demo-idle"),
            an_agent_session(id="agent-demo-running", status=AgentSessionStatus.RUNNING),
            an_agent_session(id="agent-other", project="other"),
        ]
    )
    return events, hubs, agents


# Each section as GET /sessions?status=<s>&project=&sort=&limit=50 answers it, the period's from on
# Finished only (an idle session started before it still shows); every card and every project's
# features whatever the scope; the scope's agent sessions in any status; the driver's answer.
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scope", "sort", "period_from", "sections", "agent_sessions"),
    [
        (
            None,
            "-started_at",
            None,
            {
                "waiting": WAITING[:50],
                "live": ["live-other", "live-demo"],
                "idle": ["idle-before-period"],
                "ended": ["ended-other", "ended-in-period", "ended-before-period"],
            },
            ["agent-demo-idle", "agent-demo-running", "agent-other"],
        ),
        (
            "demo",
            "last_activity_at",
            PERIOD_FROM,
            {
                "waiting": WAITING[:0:-1],
                "live": ["live-demo"],
                "idle": ["idle-before-period"],
                "ended": ["ended-in-period"],
            },
            ["agent-demo-idle", "agent-demo-running"],
        ),
    ],
    ids=["all-projects-newest-first", "one-project-in-period-by-activity"],
)
async def test_composes_sessions_screen_from_its_resources_when_read(
    scope: str | None,
    sort: str,
    period_from: datetime | None,
    *,
    sections: dict[str, list[str]],
    agent_sessions: list[str],
) -> None:
    events, hubs, agents = _inbox_world()
    assert (len(events.sessions), len(hubs.projects), len(hubs.features)) == (57, 2, 4)
    reads = ScreenReads(
        events, hubs, agents, monotonic=SteppedClock(), capabilities_wait=CAPABILITIES_WAIT
    )

    view = await reads.sessions(scope, sort, period_from, agent_reads=True)

    by_id = {item.id: item for item in events.sessions}
    assert {section: getattr(view, section) for section in SECTIONS} == {
        section: _page([by_id[session] for session in sessions])
        for section, sessions in sections.items()
    }
    assert (view.projects, view.features) == (_page(hubs.projects), _page(hubs.features))
    shown = {item.id: item for item in agents.sessions}
    assert view.agent_sessions == AgentSessionList(
        items=tuple(shown[session] for session in agent_sessions)
    )
    assert view.capabilities == CAPABILITIES


# A request the agent-session read checks refused (agent_reads false), or the sessions off (no
# agent-session port): both agent parts are None and no agent-session read is made; the sections
# still answer.
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("wired", "agent_reads"),
    [(True, False), (False, True)],
    ids=["agent-reads-not-allowed", "sessions-off"],
)
async def test_reads_no_agent_session_when_agent_reads_not_allowed(
    *, wired: bool, agent_reads: bool
) -> None:
    events, hubs, agents = _inbox_world()
    reads = ScreenReads(events, hubs, agents if wired else None, monotonic=SteppedClock())

    view = await reads.sessions(None, "-started_at", None, agent_reads=agent_reads)

    assert (view.agent_sessions, view.capabilities) == (None, None)
    assert agents.calls == []
    assert [len(getattr(view, section).items) for section in SECTIONS] == [50, 2, 1, 3]


# The driver probes claude when its answer is older than 60 s: a read waits for it only
# capabilities_wait, then answers without it while the probe goes on; overlapping reads share the
# probe; the next read after it ends takes its answer, and the one after asks the driver again,
# whose failure also answers None. No time is asserted.
@pytest.mark.anyio
async def test_answers_without_capabilities_when_driver_probe_is_slow() -> None:
    events, hubs, agents = _inbox_world()
    agents.release = asyncio.Event()
    reads = ScreenReads(events, hubs, agents, monotonic=SteppedClock(), capabilities_wait=0.01)

    # Not a time bound: a read that waited for the held probe would hang the suite instead.
    async with asyncio.timeout(5):
        first = await reads.sessions(None, "-started_at", None, agent_reads=True)
        second = await reads.sessions(None, "-started_at", None, agent_reads=True)
    probes_while_held = _count(agents.calls, "capabilities")
    agents.release.set()
    for _turn in range(100):
        if agents.answered:
            break
        await asyncio.sleep(0)
    assert agents.answered == 1
    third = await reads.sessions(None, "-started_at", None, agent_reads=True)
    agents.failure = OSError("claude could not start")
    fourth = await reads.sessions(None, "-started_at", None, agent_reads=True)

    assert (first.capabilities, second.capabilities, probes_while_held) == (None, None, 1)
    assert (len(first.waiting.items), first.agent_sessions) == (
        50,
        AgentSessionList(items=tuple(agents.sessions)),
    )
    assert third.capabilities == CAPABILITIES
    assert (fourth.capabilities, _count(agents.calls, "capabilities")) == (None, 2)


# One more event than the detail's first events page, GET /sessions/{id}/events?limit=1000.
DETAIL_EVENTS = 1_001


def a_timeline_event(session: Session, seq: int) -> TimelineEvent:
    """Event ``seq`` of ``session``: a tool call, its result or a message in turn, a second
    apart from its start."""
    kinds = (EventType.TOOL_CALL, EventType.TOOL_RESULT, EventType.MESSAGE)
    return TimelineEvent(
        event_id=f"01929a4e-6c1d-7f3a-9b2e-{seq:012x}",
        seq=seq,
        project=session.project,
        session=session.id,
        type=kinds[seq % len(kinds)],
        timestamp=session.started_at + timedelta(seconds=seq),
        received_at=None,
        latency_ms=None,
        source=EventSource.CLAUDE_CODE,
        source_id=f"{session.id}:event:{seq}",
        repo=session.repo,
        agent="main",
        workflow=None,
        step=None,
        payload={},
    )


def _detail_world() -> tuple[CountingEvents, CountingHubs]:
    """The shell's world (three features of ``demo``, one of ``other``), plus two sessions with
    1,001 events, a summary and a problems answer each: ``ended-clean`` of ``other``, ended
    with no problem, and ``live-handled`` of ``demo``, live with one problem the agent handled."""
    events, hubs = _world()
    events.sessions = [
        an_inbox_session("ended-clean", SessionStatus.ENDED, timedelta(hours=3), project="other"),
        an_inbox_session(
            "live-handled",
            SessionStatus.LIVE,
            timedelta(hours=1),
            problems=ProblemCounts(handled=1),
        ),
    ]
    handled = a_problem(resolution=Resolution.RECOVERED)
    for item in events.sessions:
        events.timeline[item.id] = [
            a_timeline_event(item, seq) for seq in range(1, DETAIL_EVENTS + 1)
        ]
        events.summaries[item.id] = SessionSummary(
            session_id=item.id,
            lines=(SummaryLine(text=f"Ran make check-fast in {item.id}", event_id=EVENT_ID),),
            generated_at=AT,
        )
        problems = (handled,) if item.problems.handled else ()
        events.problems[item.id] = a_session_problems(
            session_id=item.id, summary=(), items=problems
        )
    return events, hubs


# The session as GET /sessions/{id} answers it; its first 1,000 events of every type as GET
# /sessions/{id}/events?limit=1000 does (the 1,001st left to the next page); its summary only
# once it has ended and its problems only when it counts one (one the agent handled counts); its
# project's features; the driver's answer.
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("session", "features", "carried"),
    [
        ("ended-clean", slice(3, 4), {"summary"}),
        ("live-handled", slice(0, 3), {"problems"}),
    ],
    ids=["ended-without-problem", "live-with-handled-problem"],
)
async def test_composes_session_detail_from_its_resources_when_read(
    session: str, features: slice, carried: set[str]
) -> None:
    events, hubs = _detail_world()
    assert [item.project for item in hubs.features] == ["demo", "demo", "demo", "other"]
    assert [(item.id, item.status, item.problems) for item in events.sessions] == [
        ("ended-clean", SessionStatus.ENDED, ProblemCounts()),
        ("live-handled", SessionStatus.LIVE, ProblemCounts(handled=1)),
    ]
    assert {len(timeline) for timeline in events.timeline.values()} == {DETAIL_EVENTS}
    reads = ScreenReads(
        events,
        hubs,
        CountingAgentSessions(),
        monotonic=SteppedClock(),
        capabilities_wait=CAPABILITIES_WAIT,
    )

    view = await reads.session_detail(session, agent_reads=True)

    timeline = events.timeline[session]
    assert view == SessionDetailView(
        session=next(item for item in events.sessions if item.id == session),
        events=Page[TimelineEvent](
            items=tuple(timeline[:1000]), next_cursor="1000", total_estimate=DETAIL_EVENTS
        ),
        summary=events.summaries[session] if "summary" in carried else None,
        problems=events.problems[session] if "problems" in carried else None,
        features=_page(hubs.features[features]),
        capabilities=CAPABILITIES,
    )


# The web reads a session's problems when its problemTotal (needs_you + open + handled + by_you) is
# above 0: a session counting one problem of any of those statuses carries them.
@pytest.mark.anyio
@pytest.mark.parametrize("status", ["needs_you", "open", "by_you"])
async def test_carries_problems_when_session_counts_one_of_any_status(status: str) -> None:
    events, hubs = _detail_world()
    counted = an_inbox_session(
        "live-counted",
        SessionStatus.LIVE,
        timedelta(hours=1),
        problems=ProblemCounts.model_validate({status: 1}),
    )
    assert (sum(counted.problems.model_dump().values()), getattr(counted.problems, status)) == (
        1,
        1,
    )
    events.sessions.append(counted)
    events.timeline[counted.id] = [a_timeline_event(counted, 1)]
    events.problems[counted.id] = a_session_problems(
        session_id=counted.id, summary=(), items=(a_problem(resolution=Resolution(status)),)
    )
    reads = ScreenReads(events, hubs, CountingAgentSessions(), monotonic=SteppedClock())

    view = await reads.session_detail(counted.id, agent_reads=True)

    assert view.problems == events.problems[counted.id]
