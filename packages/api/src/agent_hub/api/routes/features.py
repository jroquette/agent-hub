"""``/features``: the feature folders of the registered hubs."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.features.feature_view import FeatureDetail, FeatureView
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["features"], responses=PROBLEM_RESPONSES)

NamePath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]


@router.get("/features")
def list_features(*, project: ProjectParam = None) -> Page[FeatureView]:
    """Features of every (or one) project."""
    raise NotImplementedInBuildError("list_features")


@router.get("/features/{project}/{slug}")
def get_feature(project: NamePath, slug: NamePath) -> FeatureDetail:
    """One feature with its acceptance criteria."""
    raise NotImplementedInBuildError("get_feature")
