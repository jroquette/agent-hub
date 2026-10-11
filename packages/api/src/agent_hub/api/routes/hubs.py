"""``/hubs``: the hub registry (registering and removing are the only writes of Phase 2)."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import PROBLEM_RESPONSES, HubCreate
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["hubs"], responses=PROBLEM_RESPONSES)


@router.get("/hubs")
def list_hubs() -> Page[HubView]:
    """Every registered hub, valid or not."""
    raise NotImplementedInBuildError("list_hubs")


@router.post("/hubs", status_code=201)
def register_hub(hub: HubCreate) -> HubView:
    """Register a hub by its path."""
    raise NotImplementedInBuildError("register_hub")


@router.delete("/hubs/{hub_id}", status_code=204, response_class=Response)
def remove_hub(hub_id: Annotated[str, Path(min_length=1, max_length=64)]) -> None:
    """Forget a hub; its events stay in the store."""
    raise NotImplementedInBuildError("remove_hub")
