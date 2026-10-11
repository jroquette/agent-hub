"""``/hubs``: the hub registry (registering and removing are the only writes of Phase 2)."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from agent_hub.api.dependencies import HubReadModelsDep
from agent_hub.api.schemas import PROBLEM_RESPONSES, HubCreate
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["hubs"], responses=PROBLEM_RESPONSES)


@router.get("/hubs")
def list_hubs(models: HubReadModelsDep) -> Page[HubView]:
    """Every registered hub, valid or not."""
    return models.list_hubs()


@router.post("/hubs", status_code=201)
def register_hub(hub: HubCreate, models: HubReadModelsDep) -> HubView:
    """Register a hub by its path."""
    return models.register_hub(hub.path)


@router.delete("/hubs/{hub_id}", status_code=204, response_class=Response)
def remove_hub(
    hub_id: Annotated[str, Path(min_length=1, max_length=64)], models: HubReadModelsDep
) -> None:
    """Forget a hub; its events stay in the store."""
    models.remove_hub(hub_id)
