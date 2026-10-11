"""``GET /live-sessions``: the Live sessions tiles."""

from fastapi import APIRouter

from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.projects.project_views import LiveTile
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["live"], responses=PROBLEM_RESPONSES)


@router.get("/live-sessions")
def list_live_sessions(*, project: ProjectParam = None) -> Page[LiveTile]:
    """Live session tiles, waiting first."""
    raise NotImplementedInBuildError("list_live_sessions")
