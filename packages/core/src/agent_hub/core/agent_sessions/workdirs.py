"""The folders a session may start in (D6, P15): the hub, its repos' checkouts and their
worktrees, never a free path.

Pure: the file system is reached through three injected functions, ``list_dir`` (the names of a
folder's sub-folders, no link followed; ``FileNotFoundError`` when it does not exist, another
``OSError`` when it cannot be read), ``realpath`` and ``stat``, and the caller's ``uid``. The
API builds a fresh listing for each request and resolves a ``workdir_id`` only by looking it up
in it, so a path, ``..`` or an id of another project never reaches the driver.

- The hub is the registered hub path. A repo is a ``hub.json`` ``repos[].dir`` sibling of the
  hub that is checked out; its real path must stay inside the hub's parent folder.
- A worktree is a folder of ``<repo>/.claude/worktrees/`` (the ``hub worktree`` layout); its
  real path must stay inside that folder of the repo's real path. At most 200 per repo, by name.
- A hub, repo or worktree is kept only when ``stat`` of its real path says it is owned by
  ``uid`` and is neither group- nor world-writable (A11): another local user cannot plant a
  folder, or a ``.claude/settings.json``, that a session would start in. A refused hub lists
  nothing. Each refusal is named in ``warnings``.
- Each workdir lists the names of its ``.claude/skills/*/`` folders (at most 200).
- ``workdir_id`` is the first 16 hex digits of SHA-256 over ``kind\\0realpath``: opaque, and
  stable while the folder stays where it is.

A folder that cannot be read is skipped and named in ``warnings``.
"""

import hashlib
import os
import stat as stat_module
from collections.abc import Callable, Sequence
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from agent_hub.core.agent_sessions.agent_session import Workdir, WorkdirList
from agent_hub.core.agent_sessions.errors import InvalidWorkdirError

MAX_WORKTREES: Final = 200
MAX_SKILLS: Final = 200
_ID_DIGITS: Final = 16

_SHARED_WRITE: Final = stat_module.S_IWGRP | stat_module.S_IWOTH


class FileStatus(Protocol):
    """The part of ``os.stat_result`` the ownership check reads."""

    @property
    def st_uid(self) -> int: ...

    @property
    def st_mode(self) -> int: ...


type ListDir = Callable[[str], Sequence[str]]
type RealPath = Callable[[str], str]
type StatPath = Callable[[str], FileStatus]
type WorkdirKind = Literal["hub", "repo", "worktree"]


class ResolvedWorkdir(BaseModel):
    """A listed workdir and its real path, where a session starts (never sent to the
    browser)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workdir: Workdir
    path: str


class WorkdirListing(BaseModel):
    """The workdirs of one project, as listed now."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[ResolvedWorkdir, ...]
    warnings: tuple[str, ...] = ()

    def view(self) -> WorkdirList:
        """What ``GET /workdirs`` answers."""
        return WorkdirList(
            items=tuple(entry.workdir for entry in self.entries), warnings=self.warnings
        )

    def resolve(self, workdir_id: str) -> ResolvedWorkdir:
        """The listed workdir with this id; ``InvalidWorkdirError`` for anything else."""
        for entry in self.entries:
            if entry.workdir.workdir_id == workdir_id:
                return entry
        raise InvalidWorkdirError(workdir_id)


def workdir_id(kind: WorkdirKind, real_path: str) -> str:
    """The opaque, stable id of a workdir."""
    digest = hashlib.sha256(f"{kind}\0{real_path}".encode()).hexdigest()
    return digest[:_ID_DIGITS]


def list_workdirs(
    hub_path: str,
    repo_dirs: Sequence[str],
    *,
    list_dir: ListDir,
    realpath: RealPath,
    stat: StatPath,
    uid: int,
) -> WorkdirListing:
    """The hub, the checked-out repos among ``repo_dirs`` and their worktrees, in that order."""
    walk = _Walk(list_dir, realpath, stat=stat, uid=uid)
    hub_real = realpath(hub_path)
    if not walk.add("hub", hub_path, hub_real, label=os.path.basename(os.path.normpath(hub_path))):
        return WorkdirListing(entries=(), warnings=tuple(walk.warnings))
    parent = os.path.dirname(hub_real)
    siblings = set(walk.names(parent, os.path.basename(parent) or parent))
    for repo in repo_dirs:
        if repo in siblings:
            _add_repo(walk, repo, parent=parent)
    return WorkdirListing(entries=tuple(walk.entries), warnings=tuple(walk.warnings))


def _add_repo(walk: _Walk, repo: str, *, parent: str) -> None:
    path = os.path.join(parent, repo)
    real = walk.realpath(path)
    if not _inside(real, parent):
        return
    if not walk.add("repo", path, real, label=repo, repo=repo):
        return
    root = os.path.join(path, ".claude", "worktrees")
    real_root = os.path.join(real, ".claude", "worktrees")
    names = sorted(walk.names(root, f"{repo}/.claude/worktrees"))
    if len(names) > MAX_WORKTREES:
        walk.warnings.append(f"{repo} has more than {MAX_WORKTREES} worktrees")
    for name in names[:MAX_WORKTREES]:
        worktree_path = os.path.join(root, name)
        worktree_real = walk.realpath(worktree_path)
        if _inside(worktree_real, real_root):
            walk.add(
                "worktree",
                worktree_path,
                worktree_real,
                label=f"{repo}/{name}",
                repo=repo,
                worktree=name,
            )


def _inside(path: str, root: str) -> bool:
    """Whether ``path`` is strictly below ``root``."""
    return path.startswith(root.rstrip(os.sep) + os.sep)


class _Walk:
    """The entries and warnings collected so far."""

    def __init__(self, list_dir: ListDir, realpath: RealPath, *, stat: StatPath, uid: int) -> None:
        self.list_dir = list_dir
        self.realpath = realpath
        self._stat = stat
        self._uid = uid
        self.entries: list[ResolvedWorkdir] = []
        self.warnings: list[str] = []
        self._seen: set[str] = set()

    def names(self, path: str, label: str) -> Sequence[str]:
        try:
            return self.list_dir(path)
        except FileNotFoundError:
            return ()
        except OSError:
            self.warnings.append(f"cannot read {label}")
            return ()

    def trusted(self, real: str, label: str) -> bool:
        """Whether ``real`` is owned by the caller and writable by no one else; a refusal is
        named in ``warnings``."""
        try:
            status = self._stat(real)
        except OSError:
            self.warnings.append(f"cannot read {label}")
            return False
        if status.st_uid != self._uid:
            self.warnings.append(f"refused {label}: not owned by the current user")
            return False
        if status.st_mode & _SHARED_WRITE:
            self.warnings.append(f"refused {label}: writable by group or others")
            return False
        return True

    def add(
        self,
        kind: WorkdirKind,
        path: str,
        real: str,
        *,
        label: str,
        repo: str | None = None,
        worktree: str | None = None,
    ) -> bool:
        """Add the workdir; ``False`` when it is refused (not trusted)."""
        identifier = workdir_id(kind, real)
        if identifier in self._seen:
            return True
        if not self.trusted(real, label):
            return False
        self._seen.add(identifier)
        skills_label = f"{label}/.claude/skills"
        skills = sorted(self.names(os.path.join(path, ".claude", "skills"), skills_label))
        workdir = Workdir(
            workdir_id=identifier,
            kind=kind,
            label=label,
            repo=repo,
            worktree=worktree,
            skills=tuple(skills[:MAX_SKILLS]),
        )
        self.entries.append(ResolvedWorkdir(workdir=workdir, path=real))
        return True
