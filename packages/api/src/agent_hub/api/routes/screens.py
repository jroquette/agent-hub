"""``/screens``: one read per screen beside the resource routes (ADR 0056)."""

from fastapi import APIRouter

from agent_hub.api.dependencies import ScreenReadsDep
from agent_hub.api.routes.projects import ProjectPath
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.screens.screen_views import PortfolioView, ProjectOverviewView, ShellView

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
