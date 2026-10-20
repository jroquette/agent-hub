"""``/features``: the feature folders of the registered hubs."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.ac_check import AcCheckRun
from agent_hub.api.dependencies import (
    AcChecksDep,
    FeatureNamesDep,
    HubReadModelsDep,
    OwnerSignOffDep,
)
from agent_hub.api.feature_names import FeatureName, FeatureNameBody, FeatureNamesView
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.features.feature_view import EvalRecord, FeatureDetail, FeatureView
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


@router.post("/features/{project}/{slug}/owner-signoff", status_code=201)
def sign_off_owner_steps(
    project: NamePath, slug: NamePath, sign_off: OwnerSignOffDep
) -> EvalRecord:
    """The owner confirms the owner steps are done: writes an ``owner-signoff`` SHIP eval over
    the ACs the Acceptance step waits on; 409 with a one-line reason, writing nothing, when none
    waits or the feature lists no AC, when one of them has a NO-SHIP as its latest eval, when the
    acceptance eval is undated or future-dated, or when not every eval was read."""
    return sign_off(project, slug)


@router.post("/features/{project}/{slug}/acs/{ac}/check-runs")
def run_ac_check(
    project: NamePath, slug: NamePath, ac: NamePath, *, checks: AcChecksDep
) -> AcCheckRun:
    """Run the check ``features.json`` records for one AC in its repo's checkout and answer its
    exit code and output (nothing is recorded; 409 for a manual AC or one with no command)."""
    return checks.run(project, slug, ac)


@router.get("/feature-names")
def list_feature_names(names: FeatureNamesDep) -> FeatureNamesView:
    """The nicknames the owner gave features on this machine (the slug stays the identity)."""
    return names.all()


@router.put("/feature-names")
def set_feature_name(body: FeatureNameBody, names: FeatureNamesDep) -> FeatureName:
    """Give a feature a nickname, or clear it with an empty name."""
    return names.set(body)
