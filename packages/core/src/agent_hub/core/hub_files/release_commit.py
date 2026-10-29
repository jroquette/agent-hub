"""The commit of the pinned platform release, as ``hub.lock`` records it (ADR 0054).

``hub sync`` looks the commit of tag ``v<platform.version>`` up only when the pin changed since the
lock (``needs_lookup``); otherwise it keeps the lock's commit while the version and the repository
in use still match (``kept_release``). The lookup itself is the CLI's (``ReleaseLookup``): this
module only reads its ``git ls-remote`` output and does no I/O.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import HubLock


@dataclass(frozen=True, kw_only=True, slots=True)
class ReleaseCommit:
    """The commit a release tag names, and the repository it was read from."""

    commit: str
    repository: str


@dataclass(frozen=True, kw_only=True, slots=True)
class LookupFailure:
    """The tag could not be read (no network, no credential, timeout, no tag): see ``reason``."""

    reason: str


# The port the CLI fills: (repository, version) to the tag's commit, or why it was not found.
type ReleaseLookup = Callable[[str, str], ReleaseCommit | LookupFailure]


def commit_from_ls_remote(text: str, version: str) -> str | None:
    """The commit of tag ``v<version>`` in ``git ls-remote`` output, else ``None``.

    An annotated tag's peeled ``^{}`` line names the commit and wins over the tag object's own
    line; a lightweight tag has only its own line. Only whole lines of a 40-hex hash, a tab and the
    exact ref count, so a first line cut by an output cap never matches.
    """
    line = re.compile(rf"([0-9a-f]{{40}})\trefs/tags/v{re.escape(version)}(\^\{{\}})?")
    own: str | None = None
    for each in text.splitlines():
        found = line.fullmatch(each)
        if found is None:
            continue
        if found.group(2) is not None:
            return found.group(1)
        own = found.group(1)
    return own


def kept_release(lock: HubLock, config: HubConfig) -> ReleaseCommit | None:
    """The lock's release commit when it still fits ``config``'s pin and repository in use."""
    if lock.platform_commit is None or lock.platform_repository is None:
        return None
    if lock.platform_version != config.platform.version:
        return None
    if lock.platform_repository != config.platform.effective_repository:
        return None
    return ReleaseCommit(commit=lock.platform_commit, repository=lock.platform_repository)


def needs_lookup(lock: HubLock, config: HubConfig) -> bool:
    """Whether a sync must look the release commit up: the pin changed since the lock.

    A lock whose version matches the pin and holds no commit asks for none (a fresh ``hub init``
    or an unchanged older hub stays offline); one whose recorded commit no longer fits does.
    """
    if lock.platform_version != config.platform.version:
        return True
    return lock.platform_commit is not None and kept_release(lock, config) is None
