"""The ``TrackerClient`` adapter ``hub`` uses for the tracker in ``hub.json`` (ADRs 0014, 0015)."""

from collections.abc import Mapping
from pathlib import Path
from typing import assert_never

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.tracker.tracker_client import TrackerClient
from agent_hub.tracker_linear.graphql import LinearGraphqlTrackerClient
from agent_hub.tracker_linear.mcp import McpTrackerClient


def resolve_tracker_client(
    config: HubConfig, environ: Mapping[str, str], *, hub_root: Path
) -> TrackerClient:
    """The adapter for ``tracker.kind`` and ``tracker.transport``.

    ``linear`` with transport ``api`` (the default) is Linear's GraphQL API; with ``mcp`` it is
    the user's Linear MCP server through ``claude -p``, run in ``hub_root``. Only the config
    decides. Nothing in ``environ`` is read here: the GraphQL adapter reads ``LINEAR_API_KEY``
    on each call, and the MCP adapter passes the environment on without it.
    """
    match config.tracker.kind:
        case "linear":
            if config.tracker.transport == "mcp":
                return McpTrackerClient(environ=environ, cwd=hub_root)
            return LinearGraphqlTrackerClient(environ=environ)
        case unreachable:
            assert_never(unreachable)
