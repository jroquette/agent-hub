"""Cross-project reads: Needs you, the activity feed and search."""

from typing import Annotated

from fastapi import APIRouter, Query

from agent_hub.api.dependencies import EventReadModelsDep, parse_filter
from agent_hub.api.schemas import (
    DEFAULT_LIMIT,
    MAX_QUERY_TEXT,
    PROBLEM_RESPONSES,
    CursorParam,
    LimitParam,
    ProjectParam,
)
from agent_hub.core.projects.project_views import ActivityItem, NeedsYouItem, SearchHit
from agent_hub.core.readmodels.filters import PageRequest, Scope
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["overview"], responses=PROBLEM_RESPONSES)


@router.get("/needs-you")
def list_needs_you(
    models: EventReadModelsDep, *, project: ProjectParam = None
) -> Page[NeedsYouItem]:
    """What waits for a person, oldest first."""
    return models.needs_you(Scope(project=project))


@router.get("/activity")
def list_activity(
    models: EventReadModelsDep,
    *,
    project: ProjectParam = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> Page[ActivityItem]:
    """Notable events, newest first."""
    return models.activity(parse_filter(PageRequest, project=project, cursor=cursor, limit=limit))


@router.get("/search")
def search(
    models: EventReadModelsDep,
    *,
    q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_TEXT)],
    project: ProjectParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> Page[SearchHit]:
    """Search ids, paths, commands and tool names."""
    page = parse_filter(PageRequest, project=project, limit=limit)
    return models.search_events(q, page)
