"""Which ``TrackerClient`` adapter ``hub`` uses for the tracker named in ``hub.json`` (ADR 0014)."""

from collections.abc import Mapping
from typing import assert_never

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.tracker.tracker_client import TrackerClient
from agent_hub.tracker_linear.graphql import LinearGraphqlTrackerClient


def resolve_tracker_client(config: HubConfig, environ: Mapping[str, str]) -> TrackerClient:
    """The adapter for ``tracker.kind``: ``linear`` is Linear's GraphQL API.

    Nothing in ``environ`` is read here: the adapter reads ``LINEAR_API_KEY`` on each call, so
    resolving without a key succeeds and the first call names the missing variable.
    """
    match config.tracker.kind:
        case "linear":
            return LinearGraphqlTrackerClient(environ=environ)
        case unreachable:
            assert_never(unreachable)
