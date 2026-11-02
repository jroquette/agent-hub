"""``/screens``: one read per screen beside the resource routes (ADR 0056)."""

from fastapi import APIRouter

from agent_hub.api.dependencies import ScreenReadsDep
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.screens.screen_views import ShellView

router = APIRouter(tags=["screens"], responses=PROBLEM_RESPONSES)


@router.get("/screens/shell")
def read_shell(screens: ScreenReadsDep, *, project: ProjectParam = None) -> ShellView:
    """The app shell's facts in one read: how many hubs are registered, every project with its
    live sessions, how many features of the scope need you, and whether any project has a
    workflow run. The feature list behind the count is kept 30 s."""
    return screens.shell(project)
