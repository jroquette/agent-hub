"""``/hubs``: the hub registry (registering and removing are the only writes of Phase 2).

A hub action (platform sync, doctor fix) reads its hub again once it is done, whatever its
outcome (a failed run may have changed files), so the next read shows it and the background
doctor checks that hub at its next tick (AGH-608).
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from agent_hub.api.dependencies import HubReadModelsDep, OptionalScreenReadsDep
from agent_hub.api.doctor_fix import DoctorFixRequest, DoctorFixResult, fix_hub
from agent_hub.api.platform_sync import (
    PlatformSyncError,
    PlatformSyncRequest,
    PlatformSyncResult,
    sync_platform,
)
from agent_hub.api.schemas import PROBLEM_RESPONSES, HubCreate
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError

router = APIRouter(tags=["hubs"], responses=PROBLEM_RESPONSES)


@router.get("/hubs")
def list_hubs(models: HubReadModelsDep) -> Page[HubView]:
    """Every registered hub, valid or not."""
    return models.list_hubs()


@router.post("/hubs", status_code=201)
def register_hub(
    hub: HubCreate, models: HubReadModelsDep, screens: OptionalScreenReadsDep
) -> HubView:
    """Register a hub by its path."""
    registered = models.register_hub(hub.path)
    # Once registered, the shell read lists the features again at its next poll, so its badge
    # counts the new hub's at once (ADR 0056).
    if screens is not None:
        screens.forget_features()
    return registered


@router.delete("/hubs/{hub_id}", status_code=204, response_class=Response)
def remove_hub(
    hub_id: Annotated[str, Path(min_length=1, max_length=64)],
    models: HubReadModelsDep,
    screens: OptionalScreenReadsDep,
) -> None:
    """Forget a hub; its events stay in the store."""
    models.remove_hub(hub_id)
    # Once removed, the shell read lists the features again at its next poll, so its badge no
    # longer counts the removed hub's (ADR 0056).
    if screens is not None:
        screens.forget_features()


@router.post("/hubs/{hub_id}/platform-sync")
def sync_hub_platform(
    hub_id: Annotated[str, Path(min_length=1, max_length=64)],
    _body: PlatformSyncRequest,
    models: HubReadModelsDep,
) -> PlatformSyncResult:
    """Pin the hub to the running release and run ``hub sync`` in it; nothing is committed."""
    hub = next((view for view in models.list_hubs().items if view.id == hub_id), None)
    if hub is None:
        raise EntityNotFoundError(entity="hub", entity_id=hub_id)
    try:
        result = sync_platform(hub.id, hub.path, running_version=hub.running_version)
    except PlatformSyncError as error:
        result = PlatformSyncResult(
            hub_id=hub.id,
            previous_version=hub.platform_pin,
            version=hub.platform_pin or hub.running_version,
            ok=False,
            exit_code=1,
            output=(str(error),),
            changed_files=(),
        )
    models.reread_hubs(written=hub.path)
    return result


@router.post("/hubs/{hub_id}/doctor-fix")
def fix_hub_findings(
    hub_id: Annotated[str, Path(min_length=1, max_length=64)],
    _body: DoctorFixRequest,
    models: HubReadModelsDep,
) -> DoctorFixResult:
    """Run ``hub doctor --fix`` in the hub: every auto-fixable finding; nothing committed."""
    hub = next((view for view in models.list_hubs().items if view.id == hub_id), None)
    if hub is None:
        raise EntityNotFoundError(entity="hub", entity_id=hub_id)
    result = fix_hub(hub.id, hub.path)
    models.reread_hubs(written=hub.path)
    return result
