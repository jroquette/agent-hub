"""The OS side of the workdir list (P15): which folders a session of a project may start in.

``scan_dirs`` names a folder's sub-folders with ``os.scandir``: directories only, and a link is
never followed (a link to a folder is not listed). ``RegisteredWorkdirs`` finds the project's
hub in the registry (the first valid registered hub naming it, as the hub read models do) and
builds a fresh ``list_workdirs`` listing over ``scan_dirs``, ``os.path.realpath`` and ``os.stat``
against ``os.geteuid()`` (a folder of another user, or one writable by group or others, is
refused, A11) on every call, so a ``workdir_id`` is only ever resolved against what is on disk
now. An unknown project raises ``EntityNotFoundError`` (404).
"""

import os
from collections.abc import Sequence

from agent_hub.core.agent_sessions.workdirs import (
    ListDir,
    RealPath,
    StatPath,
    WorkdirListing,
    list_workdirs,
)
from agent_hub.core.hubs.hub_document import read_hub_document
from agent_hub.core.hubs.hub_registry import HubFileReader, HubRegistry, HubRegistryError
from agent_hub.core.readmodels.read_ports import EntityNotFoundError


def scan_dirs(path: str) -> Sequence[str]:
    """The names of ``path``'s sub-folders, links not followed; ``FileNotFoundError`` when it
    does not exist, another ``OSError`` when it cannot be read."""
    with os.scandir(path) as entries:
        return [entry.name for entry in entries if entry.is_dir(follow_symlinks=False)]


class RegisteredWorkdirs:
    """``project -> WorkdirListing`` over the hub registry and the file system."""

    def __init__(
        self,
        *,
        registry: HubRegistry,
        reader: HubFileReader,
        running_version: str,
        list_dir: ListDir = scan_dirs,
        realpath: RealPath = os.path.realpath,
        stat: StatPath = os.stat,
        uid: int | None = None,
    ) -> None:
        self._registry = registry
        self._reader = reader
        self._running = running_version
        self._list_dir = list_dir
        self._realpath = realpath
        self._stat = stat
        self._uid = os.geteuid() if uid is None else uid

    def __call__(self, project: str) -> WorkdirListing:
        """The project's workdirs as listed now; ``EntityNotFoundError`` when no valid
        registered hub names it."""
        found = self._hub_of(project)
        if found is None:
            raise EntityNotFoundError(entity="project", entity_id=project)
        hub_path, repo_dirs = found
        return list_workdirs(
            hub_path,
            repo_dirs,
            list_dir=self._list_dir,
            realpath=self._realpath,
            stat=self._stat,
            uid=self._uid,
        )

    def _hub_of(self, project: str) -> tuple[str, tuple[str, ...]] | None:
        try:
            entries = self._registry.entries()
        except HubRegistryError:
            return None
        for entry in entries:
            document = read_hub_document(
                self._reader.read_hub_json(entry.path), running_version=self._running
            )
            config = document.config
            if config is not None and config.project.name == project:
                return entry.path, tuple(str(repo.dir) for repo in config.repos)
        return None
