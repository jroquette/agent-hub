"""The ``TrackerClient`` adapter ``hub`` uses for the tracker in ``hub.json`` (ADRs 0014, 0015)."""

from collections.abc import Mapping
from pathlib import Path
from typing import Final, assert_never

from agent_hub.cli.hub_config_reader import FILE_LABEL
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.tracker.tracker_client import TrackerClient
from agent_hub.tracker_linear.graphql import LinearGraphqlTrackerClient
from agent_hub.tracker_linear.mcp import McpTrackerClient

KEY_VARIABLE: Final = "LINEAR_API_KEY"
_TRANSPORT_TEXTS: Final = {
    "api": 'tracker: Linear API (tracker.transport "api")',
    "mcp": 'tracker: Linear MCP via claude -p (tracker.transport "mcp")',
}


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


def missing_key_line(config: HubConfig, environ: Mapping[str, str], *, command: str) -> str | None:
    """The line ``hub <command>`` stops on when transport ``api`` has no key; None otherwise.

    An empty ``LINEAR_API_KEY`` counts as absent. Only its presence is read, never shown.
    """
    if config.tracker.transport != "api" or environ.get(KEY_VARIABLE):
        return None
    return (
        f"hub {command}: {KEY_VARIABLE} is not set; export it, or set"
        f' tracker.transport: "mcp" in {FILE_LABEL} to reach Linear through its MCP server'
        " with claude -p"
    )


def transport_line(config: HubConfig) -> str:
    """The one stderr line naming the transport a command uses (ADR 0015)."""
    return _TRANSPORT_TEXTS[config.tracker.transport]
