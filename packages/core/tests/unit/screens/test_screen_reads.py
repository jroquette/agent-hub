"""The screen reads (ADR 0056) over counting fakes of the read ports.

The shell read: ``hub_count`` from ``list_hubs``; every project of ``list_projects`` in its order,
whatever the scope; the features of the scope that need you, counted over a fresh
``list_live_sessions(scope)`` and a feature list kept per scope for 30 s (the Features list's own
refresh), which ``forget_features()`` drops; ``has_workflow_runs`` from one workflow run of any
project. The clock is the read's ``monotonic`` keyword, moved by the test.

The portfolio read (Home): every project of ``list_projects`` whatever the scope, what
``needs_you`` answers for the scope, and the scope's first ``activity`` page of 20 items
(Home's activity page), each as the read port answers it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_hub.core.features.feature_view import FeatureView
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.projects.project_views import (
    ActivityItem,
    LiveTile,
    NeedsYouItem,
    ProjectSummary,
)
from agent_hub.core.readmodels.filters import PageRequest, RunFilter, Scope
from agent_hub.core.readmodels.page import Page
from agent_hub.core.runs.workflow_run import WorkflowRun
from agent_hub.core.screens.screen_reads import ScreenReads
from agent_hub.core.screens.screen_views import PortfolioView, ShellProject, ShellView
from agent_hub.core.testing.read_model_builders import (
    a_feature_view,
    a_hub_view,
    a_project_summary,
    a_run,
    a_session_label,
)

AT = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
START = 1_000.0


def _page[T](items: Sequence[T]) -> Page[T]:
    return Page[T](items=tuple(items), next_cursor=None, total_estimate=len(items))


@dataclass
class CountingEvents:
    """The event reads the screen reads make, over lists, filtered and cut to a page as the
    read models do; records each call."""

    tiles: list[LiveTile] = field(default_factory=list)
    runs: list[WorkflowRun] = field(default_factory=list)
    needs: list[NeedsYouItem] = field(default_factory=list)
    feed: list[ActivityItem] = field(default_factory=list)
    calls: list[tuple[str, object]] = field(default_factory=list)

    def list_live_sessions(self, scope: Scope) -> Page[LiveTile]:
        self.calls.append(("list_live_sessions", scope))
        return _page([tile for tile in self.tiles if scope.project in {None, tile.project}])

    def list_runs(self, run_filter: RunFilter) -> Page[WorkflowRun]:
        self.calls.append(("list_runs", run_filter))
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


@dataclass
class CountingHubs:
    """The hub reads the shell makes, over lists; records each call."""

    hubs: list[HubView] = field(default_factory=list)
    projects: list[ProjectSummary] = field(default_factory=list)
    features: list[FeatureView] = field(default_factory=list)
    calls: list[tuple[str, object]] = field(default_factory=list)

    def list_hubs(self) -> Page[HubView]:
        self.calls.append(("list_hubs", None))
        return _page(self.hubs)

    def list_projects(self) -> Page[ProjectSummary]:
        self.calls.append(("list_projects", None))
        return _page(self.projects)

    def list_features(self, scope: Scope) -> Page[FeatureView]:
        self.calls.append(("list_features", scope))
        return _page([item for item in self.features if scope.project in {None, item.project}])


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
