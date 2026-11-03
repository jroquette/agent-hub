"""``/screens``: one read per screen beside the resource routes (ADR 0056)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from agent_hub.api.dependencies import AgentSessionReadsDep, ScreenReadsDep, parse_filter
from agent_hub.api.routes.projects import ProjectPath
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.readmodels.filters import SessionFilter, SessionSort
from agent_hub.core.screens.screen_views import (
    PortfolioView,
    ProjectOverviewView,
    SessionsView,
    ShellView,
)

router = APIRouter(tags=["screens"], responses=PROBLEM_RESPONSES)


@router.get("/screens/shell")
def read_shell(screens: ScreenReadsDep, *, project: ProjectParam = None) -> ShellView:
    """The app shell's facts in one read: how many hubs are registered, every project with its
    live sessions, how many features of the scope need you, and whether any project has a
    workflow run. The feature list behind the count is kept 30 s."""
    return screens.shell(project)


@router.get("/screens/portfolio")
def read_portfolio(screens: ScreenReadsDep, *, project: ProjectParam = None) -> PortfolioView:
    """Home's first view in one read: every project's card (as ``GET /projects``), what needs
    you in the scope (as ``GET /needs-you``) and the scope's first activity page of 20 items (as
    ``GET /activity?limit=20``)."""
    return screens.portfolio(project)


@router.get("/screens/project-overview/{project}")
def read_project_overview(project: ProjectPath, screens: ScreenReadsDep) -> ProjectOverviewView:
    """The Project overview's first view in one read: the project's header, findings, every
    card, what needs you, its first 200 runs, ``now.md``, features, repos and config, each as its
    route answers it, and ``recent_sessions``: of its 200 sessions newest by last activity, those
    of the issues with a session active in the last 7 days. An unknown project answers 404, as
    ``GET /projects/{project}`` does."""
    return screens.project_overview(project)


@router.get("/screens/sessions")
async def read_sessions(
    screens: ScreenReadsDep,
    agent_reads: AgentSessionReadsDep,
    *,
    project: ProjectParam = None,
    sort: SessionSort = "-started_at",
    started_from: Annotated[datetime | None, Query(alias="from")] = None,
) -> SessionsView:
    """The Sessions inbox's first view in one read: each status section's first page of 50 (as
    ``GET /sessions?status=&project=&sort=&limit=50``, ``from`` on Finished only), every
    project's card (as ``GET /projects``) and every project's features (as ``GET /features``).
    ``agent_sessions`` and ``capabilities`` answer as ``GET /agent-sessions?project=`` and ``GET
    /agent-sessions/capabilities`` only for a request those routes would answer (the launch
    cookie, this server's pages, the sessions on), else null; ``capabilities`` is also null while
    the driver is still checking ``claude``."""
    period = parse_filter(SessionFilter, project=project, sort=sort, started_from=started_from)
    return await screens.sessions(project, sort, period.started_from, agent_reads=agent_reads)
