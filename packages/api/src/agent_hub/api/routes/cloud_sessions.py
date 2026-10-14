"""``/agent-sessions/cloud``: start a cloud session through ``claude --cloud`` and follow it up
(D8). Included before the agent-session routes, so ``/cloud`` is never read as an id."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import CloudSessionsDep
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.agent_sessions.agent_session import (
    CLOUD_ID_PATTERN,
    CloudMessage,
    CloudSession,
    CloudSessionList,
    StartCloud,
)

router = APIRouter(
    prefix="/agent-sessions/cloud", tags=["agent-sessions"], responses=PROBLEM_RESPONSES
)

CloudIdPath = Annotated[str, Path(pattern=CLOUD_ID_PATTERN)]


@router.get("")
async def list_cloud_sessions(
    cloud: CloudSessionsDep, *, project: ProjectParam = None
) -> CloudSessionList:
    """The cloud sessions started from here, newest first, at most 50."""
    return await cloud.list_cloud(project)


@router.post("", status_code=201)
async def start_cloud_session(body: StartCloud, cloud: CloudSessionsDep) -> CloudSession:
    """Start a cloud session with a task; answers its claude.ai/code link and teleport command."""
    return await cloud.start(body)


@router.post("/{cloud_id}/messages")
async def follow_up_cloud_session(
    cloud_id: CloudIdPath, body: CloudMessage, cloud: CloudSessionsDep
) -> CloudSession:
    """Send one follow-up message to a cloud session (cloud: limited control)."""
    return await cloud.follow_up(cloud_id, body)
