"""``/features``: the feature folders of the registered hubs."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import HubReadModelsDep
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.features.feature_view import FeatureDetail, FeatureView
from agent_hub.core.features.ticket_view import FeatureTickets
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["features"], responses=PROBLEM_RESPONSES)

NamePath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]


@router.get("/features")
def list_features(models: HubReadModelsDep, *, project: ProjectParam = None) -> Page[FeatureView]:
    """Features of every (or one) project."""
    return models.list_features(Scope(project=project))


@router.get("/features/{project}/{slug}")
def get_feature(project: NamePath, slug: NamePath, models: HubReadModelsDep) -> FeatureDetail:
    """One feature with its acceptance criteria."""
    return models.get_feature(project, slug)


@router.get("/features/{project}/{slug}/tickets")
def get_feature_tickets(
    project: NamePath, slug: NamePath, models: HubReadModelsDep
) -> FeatureTickets:
    """One feature's tickets with their planning and golden path; Linear when connected, else
    the plan with a notice (always 200 for a known feature)."""
    return models.feature_tickets(project, slug)
