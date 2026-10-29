"""The commit of the pinned platform release, as ``hub.lock`` records it (ADR 0054).

RED stub for AGH-603 (plan LOCK-1 commit 11): the names the tests import, with no logic yet.
"""

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import HubLock


class ReleaseCommit:
    """The commit a release tag names, and the repository it was read from."""

    commit: str
    repository: str

    def __init__(self, *, commit: str, repository: str) -> None:
        raise NotImplementedError


def commit_from_ls_remote(text: str, version: str) -> str | None:
    """The commit of tag ``v<version>`` in ``git ls-remote`` output, else ``None``."""
    raise NotImplementedError


def kept_release(lock: HubLock, config: HubConfig) -> ReleaseCommit | None:
    """The lock's release commit when it still fits ``config``'s pin and repository."""
    raise NotImplementedError


def needs_lookup(lock: HubLock, config: HubConfig) -> bool:
    """Whether a sync must look the release commit up: the pin changed since the lock."""
    raise NotImplementedError
