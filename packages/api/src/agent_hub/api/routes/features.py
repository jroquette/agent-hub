"""``/features``: the feature folders of the registered hubs."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.ac_check import AcCheckRun
from agent_hub.api.change_request_files import ChangeRequestDecisionBody
from agent_hub.api.dependencies import (
    AcChecksDep,
    ChangeRequestDecisionsDep,
    EventReadModelsDep,
    FeatureNamesDep,
    HubReadModelsDep,
    OwnerSignOffDep,
)
from agent_hub.api.feature_names import FeatureName, FeatureNameBody, FeatureNamesView
from agent_hub.api.owner_signoff_files import OwnerSignOffBody
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.features.change_request_decision import OpenRunGates, with_open_gates
from agent_hub.core.features.feature_view import (
    ChangeRequestView,
    EvalRecord,
    FeatureDetail,
    FeatureView,
)
from agent_hub.core.features.ticket_view import FeatureTickets, TicketRecords
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EventReadModels

router = APIRouter(tags=["features"], responses=PROBLEM_RESPONSES)

NamePath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]


@router.get("/features")
def list_features(models: HubReadModelsDep, *, project: ProjectParam = None) -> Page[FeatureView]:
    """Features of every (or one) project."""
    return models.list_features(Scope(project=project))


@router.get("/features/{project}/{slug}")
def get_feature(
    project: NamePath, slug: NamePath, *, models: HubReadModelsDep, events: EventReadModelsDep
) -> FeatureDetail:
    """One feature with its acceptance criteria; each open change request carries the open gate
    of its run that answers it (``approval_id``), null when the run has none."""
    detail = models.get_feature(project, slug)
    requests = _gated(project, detail.change_requests, events)
    return detail.model_copy(update={"change_requests": requests})


@router.get("/features/{project}/{slug}/tickets")
def get_feature_tickets(
    project: NamePath, slug: NamePath, models: HubReadModelsDep
) -> FeatureTickets:
    """One feature's tickets with their planning and golden path; Linear when connected, else
    the plan with a notice (always 200 for a known feature)."""
    return models.feature_tickets(project, slug)


@router.get("/features/{project}/{slug}/tickets/{ticket}")
def get_ticket_records(
    project: NamePath,
    slug: NamePath,
    ticket: NamePath,
    *,
    models: HubReadModelsDep,
    events: EventReadModelsDep,
) -> TicketRecords:
    """One ticket's records the ticket panel shows: its context brief and ticket plan, every
    preflight run (local notes, discoveries) and the change requests it asks or is held by, each
    open one with its run's open gate; 404 when the feature does not list the ticket."""
    records = models.ticket_records(project, slug, ticket)
    requests = _gated(project, records.change_requests, events)
    return records.model_copy(update={"change_requests": requests})


@router.post("/features/{project}/{slug}/change-requests/{n}/decision", status_code=201)
def decide_change_request(
    project: NamePath,
    slug: NamePath,
    n: Annotated[int, Path(ge=1, le=999_999)],
    *,
    body: ChangeRequestDecisionBody,
    decide: ChangeRequestDecisionsDep,
) -> ChangeRequestView:
    """The owner decides a plan change request whose run has no open gate (abandoned, or its
    record lost): creates ``change-requests/<n>.decision.md`` once with the hub's person as
    ``decided_by``, never editing the request; the next ``/implement`` of its ticket reads it.
    409 while the run's gate is open (answer it through ``approval_id``), once decided, or with
    no person to record; 422 for a decline without a note."""
    return decide(project, slug, n, decision=body.decision, note=body.note)


def _gated(
    project: str, requests: tuple[ChangeRequestView, ...], events: EventReadModels
) -> tuple[ChangeRequestView, ...]:
    """The requests with their open gates, read only when one is open."""
    if not any(request.status == "open" and request.run_id for request in requests):
        return requests
    return with_open_gates(requests, OpenRunGates(events).of(project))


@router.post("/features/{project}/{slug}/owner-signoff", status_code=201)
def sign_off_owner_steps(
    project: NamePath,
    slug: NamePath,
    *,
    sign_off: OwnerSignOffDep,
    body: OwnerSignOffBody | None = None,
) -> EvalRecord:
    """The owner settles the owner steps. Without a body: writes an ``owner-signoff`` SHIP eval
    over the ACs the Acceptance step waits on; 409 with a one-line reason, writing nothing, when
    none waits or the feature lists no AC, when one of them has a NO-SHIP as its latest eval, when
    the acceptance eval is undated or future-dated, or when not every eval was read. With
    ``delivery``, settles that SHIP-WITH-OWNER-STEPS eval only: ``decision`` ``done`` writes a SHIP
    over its waiting ACs, ``more_work`` a NO-SHIP; ``note`` is the owner's words. A ``delivery``
    naming the acceptance eval covers what the Acceptance step waits on, with the no-body
    refusals, except that ``more_work`` is not refused over ACs an agent's eval reopened; either
    decision there is refused once an owner decision newer than the acceptance eval settled it
    (its SHIP signed every waiting AC off, or its NO-SHIP is still the latest eval of one)."""
    if body is None:
        return sign_off(project, slug)
    return sign_off(project, slug, delivery=body.delivery, decision=body.decision, note=body.note)


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
