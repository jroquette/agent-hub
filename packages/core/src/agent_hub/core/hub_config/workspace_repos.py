"""The repos a hub's workspace holds: each one's folder and its GitHub ``owner/name``."""

from typing import NamedTuple

from agent_hub.core.hub_config.model import HubConfig


class WorkspaceRepo(NamedTuple):
    """One ``repos`` entry as the workspace sees it: the folder next to the hub, and its source."""

    dir: str
    github: str


def workspace_repos(config: HubConfig) -> tuple[WorkspaceRepo, ...]:
    """Every repo of ``hub.json``, in its order; ``hub setup`` and the generator read this list."""
    return tuple(WorkspaceRepo(repo.dir, repo.github) for repo in config.repos)
