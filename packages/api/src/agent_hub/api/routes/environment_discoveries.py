"""``/projects/{project}/environment-discoveries``: find services with a read-only Claude session.

Every route is one call to ``EnvironmentDiscoveries`` (ADR 0043). Nothing here writes
``hub.json``: the web app applies the rows the person picks through
``POST /projects/{project}/config/environments`` (a batch). The routes follow the agent-session
access rules (``session_access``).
"""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import EnvironmentDiscoveriesDep
from agent_hub.api.routes.projects import ProjectPath
from agent_hub.api.schemas import PROBLEM_RESPONSES
from agent_hub.core.environment_discovery.discovery import (
    DISCOVERY_ID_PATTERN,
    EnvironmentDiscovery,
    StartEnvironmentDiscovery,
)
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["environment-discoveries"], responses=PROBLEM_RESPONSES)

DISCOVERIES = "/projects/{project}/environment-discoveries"
DiscoveryIdPath = Annotated[str, Path(pattern=DISCOVERY_ID_PATTERN)]


@router.post(DISCOVERIES)
async def start_environment_discovery(
    project: ProjectPath, body: StartEnvironmentDiscovery, discoveries: EnvironmentDiscoveriesDep
) -> EnvironmentDiscovery:
    """Start a read-only Claude session that reads the picked repos and proposes environments,
    services and addresses; 422 naming each repo or environment the config does not hold."""
    return await discoveries.start(project, body)


@router.get(DISCOVERIES)
async def list_environment_discoveries(
    project: ProjectPath, discoveries: EnvironmentDiscoveriesDep
) -> Page[EnvironmentDiscovery]:
    """The project's discoveries not discarded, newest first."""
    return await discoveries.list(project)


@router.get(DISCOVERIES + "/{discovery_id}")
async def get_environment_discovery(
    project: ProjectPath, discovery_id: DiscoveryIdPath, discoveries: EnvironmentDiscoveriesDep
) -> EnvironmentDiscovery:
    """One discovery: its session's state and, once Claude finished, the checked proposal with
    each item's status against the config of now."""
    return await discoveries.get(project, discovery_id)


@router.delete(DISCOVERIES + "/{discovery_id}", status_code=204)
async def discard_environment_discovery(
    project: ProjectPath, discovery_id: DiscoveryIdPath, discoveries: EnvironmentDiscoveriesDep
) -> None:
    """Discard a discovery (its session is ended when it still works)."""
    await discoveries.discard(project, discovery_id)
