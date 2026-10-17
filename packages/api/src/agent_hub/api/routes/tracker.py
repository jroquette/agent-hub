"""``/tracker/linear``: connect hub web to Linear from Settings, and check that it works."""

from typing import Annotated

from fastapi import APIRouter, Query

from agent_hub.api.dependencies import LinearConnectionDep
from agent_hub.api.linear_connection import LinearConnectionView, LinearKeyBody
from agent_hub.api.schemas import PROBLEM_RESPONSES

router = APIRouter(tags=["tracker"], responses=PROBLEM_RESPONSES)


@router.get("/tracker/linear")
def get_linear_connection(
    linear: LinearConnectionDep, *, fresh: Annotated[bool, Query()] = False
) -> LinearConnectionView:
    """Whether hub web reads Linear, as whom, or why not (checked against Linear)."""
    return linear.status(fresh=fresh)


@router.put("/tracker/linear")
def connect_linear(body: LinearKeyBody, linear: LinearConnectionDep) -> LinearConnectionView:
    """Check a Linear API key and save it on this machine when Linear accepts it."""
    return linear.connect(body.api_key)


@router.delete("/tracker/linear")
def disconnect_linear(linear: LinearConnectionDep) -> LinearConnectionView:
    """Forget the key saved from Settings."""
    return linear.disconnect()
