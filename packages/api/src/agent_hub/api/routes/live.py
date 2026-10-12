"""``GET /live-sessions``: the Live sessions tiles."""

from fastapi import APIRouter

from agent_hub.api.dependencies import EventReadModelsDep
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.projects.project_views import LiveTile
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["live"], responses=PROBLEM_RESPONSES)


@router.get("/live-sessions")
def list_live_sessions(
    models: EventReadModelsDep, *, project: ProjectParam = None
) -> Page[LiveTile]:
    """Live session tiles, waiting first."""
    return models.list_live_sessions(Scope(project=project))
