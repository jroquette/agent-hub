"""The screen reads (ADR 0056): each screen's first view in one call, over the read ports.

Each read composes the existing read use cases: it adds no data source, writes nothing and never
calls the tracker. The shell read keeps each scope's feature list for ``FEATURES_FRESH_SECONDS``
(the Features list's own refresh), so the shell's 5 s poll reads the live tiles again but not every
feature folder; the routes that write feature records call ``forget_features()``.

The Sessions read fills its agent-session parts only when the caller says the request may read
them, and takes the driver's capabilities only when they answer within ``capabilities_wait``: a
slower probe goes on, kept and shared by the reads that overlap it, and the next read takes its
answer.
"""

import asyncio
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

from agent_hub.core.agent_sessions.agent_session import AgentSessionList
from agent_hub.core.agent_sessions.control import AgentSessionCommands
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.features.feature_view import FeatureView
from agent_hub.core.features.owner_needs import features_needing_you
from agent_hub.core.readmodels.filters import (
    PageRequest,
    RunFilter,
    Scope,
    SessionFilter,
    SessionSort,
)
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EventReadModels, HubReadModels
from agent_hub.core.screens.screen_views import (
    PortfolioView,
    ProjectOverviewView,
    SessionsView,
    ShellProject,
    ShellView,
)
from agent_hub.core.sessions.session import Session, SessionStatus

FEATURES_FRESH_SECONDS: Final = 30.0
# The scopes whose feature list is kept: All projects and a few projects at once.
FEATURE_SCOPES_KEPT: Final = 8
# Home's first activity page, the web's ACTIVITY_PAGE: the part it writes under that page's key.
ACTIVITY_PAGE: Final = 20
# The overview's runs and sessions pages, the web's (its runs query and SESSIONS_READ).
OVERVIEW_PAGE: Final = 200
# Recent work's period, the web's WEEK_MS: a session active this long ago or less counts.
RECENT_WORK: Final = timedelta(days=7)
# How long the Sessions read waits for the driver's capabilities: a cached answer comes at once,
# while a probe of ``claude`` (up to 5 s) must not hold the screen's first paint.
CAPABILITIES_WAIT_SECONDS: Final = 0.05
# The inbox's status sections and their page, the web's sectionQueries and PAGE_SIZE.
INBOX_SECTIONS: Final = (
    SessionStatus.WAITING,
    SessionStatus.LIVE,
    SessionStatus.IDLE,
    SessionStatus.ENDED,
)
INBOX_PAGE: Final = 50


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ScreenReads:
    """The screen reads over the event and hub read models."""

    def __init__(
        self,
        events: EventReadModels,
        hubs: HubReadModels,
        agent_sessions: AgentSessionCommands | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] = _utc_now,
        capabilities_wait: float = CAPABILITIES_WAIT_SECONDS,
    ) -> None:
        self._events = events
        self._hubs = hubs
        self._agent_sessions = agent_sessions
        self._monotonic = monotonic
        self._clock = clock
        self._capabilities_wait = capabilities_wait
        # The driver's capabilities probe still to be taken, kept so the loop cannot drop it.
        self._probe: asyncio.Task[DriverCapabilities] | None = None
        self._features: OrderedDict[str | None, tuple[float, tuple[FeatureView, ...]]] = (
            OrderedDict()
        )
        # Bumped by forget_features(), so a list read before a write is never kept after it.
        self._generation = 0
        self._guard = threading.Lock()

    def shell(self, scope: str | None) -> ShellView:
        """The app shell's facts: the registered hubs, every project for the switcher, the
        features of ``scope`` that need you, and whether any project has a workflow run."""
        features = self._scope_features(scope)
        tiles = self._events.list_live_sessions(Scope(project=scope)).items if features else ()
        runs = self._events.list_runs(RunFilter(kind="workflow", limit=1))
        return ShellView(
            hub_count=len(self._hubs.list_hubs().items),
            projects=tuple(
                ShellProject(name=project.name, live_sessions=project.live_sessions)
                for project in self._hubs.list_projects().items
            ),
            features_needing_you=features_needing_you(features, tiles),
            has_workflow_runs=bool(runs.items),
        )

    def portfolio(self, scope: str | None) -> PortfolioView:
        """Home's first view: every project's card, what needs you in ``scope`` and its newest
        activity page, each as its resource route answers it."""
        return PortfolioView(
            projects=self._hubs.list_projects(),
            needs_you=self._events.needs_you(Scope(project=scope)),
            activity=self._events.activity(PageRequest(project=scope, limit=ACTIVITY_PAGE)),
        )

    def project_overview(self, project: str) -> ProjectOverviewView:
        """The Project overview's first view of ``project``: its resources' first pages, each as
        its route answers it, and the sessions of the issues worked on in the last 7 days."""
        # First, so an unknown project answers the header's own not-found error.
        detail = self._hubs.get_project(project)
        scope = Scope(project=project)
        sessions = self._events.list_sessions(
            SessionFilter(project=project, limit=OVERVIEW_PAGE, sort="-last_activity_at")
        ).items
        recent = _of_issues_worked_on(sessions, self._clock() - RECENT_WORK)
        return ProjectOverviewView(
            project=detail,
            findings=self._hubs.doctor_findings(scope),
            projects=self._hubs.list_projects(),
            needs_you=self._events.needs_you(scope),
            runs=self._events.list_runs(RunFilter(project=project, limit=OVERVIEW_PAGE)),
            now=self._hubs.project_now(project),
            features=self._hubs.list_features(scope),
            repos=self._hubs.project_repos(project),
            config=self._hubs.hub_config(project),
            recent_sessions=Page[Session](items=recent, total_estimate=len(recent)),
            has_sessions=bool(sessions),
        )

    async def sessions(
        self,
        project: str | None,
        sort: SessionSort,
        from_: datetime | None,
        *,
        agent_reads: bool,
    ) -> SessionsView:
        """The Sessions inbox's first view for ``project``, ``sort`` and the period ``from_``:
        each status section's first page of 50 as ``GET /sessions`` answers it (``from_`` bounds
        Finished only), every project's card and every project's features; and, only when
        ``agent_reads`` and the sessions are on, the scope's agent sessions and the driver's
        capabilities (these only when they answer within the wait), else None."""
        sections = (
            asyncio.to_thread(
                self._events.list_sessions,
                SessionFilter(
                    project=project,
                    status=status,
                    started_from=from_ if status is SessionStatus.ENDED else None,
                    sort=sort,
                    limit=INBOX_PAGE,
                ),
            )
            for status in INBOX_SECTIONS
        )
        (waiting, live, idle, ended), projects, features, agent_parts = await asyncio.gather(
            asyncio.gather(*sections),
            asyncio.to_thread(self._hubs.list_projects),
            asyncio.to_thread(self._hubs.list_features, Scope()),
            self._agent_parts(project, agent_reads=agent_reads),
        )
        return SessionsView(
            waiting=waiting,
            live=live,
            idle=idle,
            ended=ended,
            projects=projects,
            agent_sessions=agent_parts[0],
            capabilities=agent_parts[1],
            features=features,
        )

    def forget_features(self) -> None:
        """Drop every kept feature list, after a write of a feature record."""
        with self._guard:
            self._features.clear()
            self._generation += 1

    async def _agent_parts(
        self, project: str | None, *, agent_reads: bool
    ) -> tuple[AgentSessionList | None, DriverCapabilities | None]:
        agent_sessions = self._agent_sessions
        if agent_sessions is None or not agent_reads:
            return None, None
        listed = await agent_sessions.list_sessions(project=project, status=None)
        return listed, await self._capabilities(agent_sessions)

    async def _capabilities(
        self, agent_sessions: AgentSessionCommands
    ) -> DriverCapabilities | None:
        """The driver's answer when it comes within the wait; else None while its probe goes on,
        kept for the next read (one probe at a time, on this event loop)."""
        probe = self._probe
        if probe is None or probe.get_loop() is not asyncio.get_running_loop():
            probe = asyncio.create_task(agent_sessions.capabilities())
            self._probe = probe
        try:
            answer: DriverCapabilities | None = await asyncio.wait_for(
                asyncio.shield(probe), self._capabilities_wait
            )
        except TimeoutError:
            return None
        except Exception:  # noqa: BLE001 - a failed probe answers None; the web reads the route
            answer = None
        if self._probe is probe:
            self._probe = None
        return answer

    def _scope_features(self, scope: str | None) -> tuple[FeatureView, ...]:
        now = self._monotonic()
        with self._guard:
            kept = self._features.get(scope)
            if kept is not None and now - kept[0] < FEATURES_FRESH_SECONDS:
                return kept[1]
            generation = self._generation
        features = self._hubs.list_features(Scope(project=scope)).items
        with self._guard:
            if generation == self._generation:
                self._features[scope] = (now, features)
                self._features.move_to_end(scope)
                while len(self._features) > FEATURE_SCOPES_KEPT:
                    self._features.popitem(last=False)
        return features


def _of_issues_worked_on(sessions: Sequence[Session], since: datetime) -> tuple[Session, ...]:
    """The ``sessions`` whose issue has a session among them active at ``since`` or later, in
    their order: the sessions the overview's Recent work reads (``model.ts`` keeps the week's)."""
    worked_on = {
        issue
        for session in sessions
        if session.last_activity_at >= since and (issue := _issue_of(session)) is not None
    }
    return tuple(session for session in sessions if _issue_of(session) in worked_on)


def _issue_of(session: Session) -> str | None:
    """The session's issue as the web reads it (``issueOf``): its label's, else its own, upper
    case."""
    label = session.label
    issue = label.issue if label is not None and label.issue is not None else session.issue
    return None if issue is None else issue.upper()
