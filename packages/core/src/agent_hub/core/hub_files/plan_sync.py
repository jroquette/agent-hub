"""The sync planner (ADR 0009, ADR 0011): what ``hub sync`` changes in a hub, decided in memory.

``plan_sync`` takes the render, the config, the lock read back with its exact bytes, and a snapshot
of the planned paths. It returns a ``SyncPlan``: the leftovers to remove, the paths to delete, the
folders to make, then the writes (files, links, and ``hub.lock`` last when its bytes change), with
one verb per changed path. Or it returns ``SyncConflicts`` naming every path it may not touch, each
with its cause or both contents. It does no I/O; the generator's file adapter applies the plan.

Each path is decided in this order (plan erratum E5): an ancestor that is a link or not a folder,
then a link on disk that resolves outside the hub, then "equal to the render" (clean, whatever the
lock says, so a file an interrupted sync already wrote is never a conflict), then the type rules,
then the ownership rules. ``hub.json`` is the project's: never compared, written or deleted.
"""

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    HubLock,
    LockEntry,
    ManagedFileEntry,
    ManagedLinkEntry,
    SeededEntry,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.plan_init import (
    FileWrite,
    LinkWrite,
    PathProblem,
    _ancestor_problem,
    _ancestors,
    _check_render,
    _content,
    _is_leftover,
    _missing_folders,
    _type_problem,
)
from agent_hub.core.hub_files.rendered_file import Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry, TreeSnapshot


class Verb(StrEnum):
    """What a sync does at a path, as its report line says it."""

    CREATED = "created"
    RESTORED = "restored"
    UPDATED = "updated"
    DELETED = "deleted"


@dataclass(frozen=True, kw_only=True, slots=True)
class SyncChange:
    """One changed path and what the sync does there."""

    path: str
    verb: Verb


@dataclass(frozen=True, kw_only=True, slots=True)
class ContentConflict:
    """A managed file whose bytes differ from both its lock entry and its render."""

    path: str
    on_disk: bytes
    render: bytes


type SyncProblem = PathProblem | ContentConflict


@dataclass(frozen=True, kw_only=True, slots=True)
class SyncConflicts:
    """Every conflicted path, sorted by path: nothing is written or deleted."""

    problems: tuple[SyncProblem, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class SyncPlan:
    """What a sync does, in the order the adapter applies it.

    ``leftovers``, ``deletes``, ``folders`` and ``changes`` are sorted by path; ``writes`` holds
    files, then links, each in path order, then ``hub.lock`` when ``lock_written``. ``lock`` is the
    lock of the render, written or not.
    """

    leftovers: tuple[str, ...]
    deletes: tuple[str, ...]
    folders: tuple[str, ...]
    writes: tuple[FileWrite | LinkWrite, ...]
    changes: tuple[SyncChange, ...]
    lock: HubLock
    lock_written: bool

    @property
    def pending(self) -> bool:
        """Whether applying the plan changes anything on disk."""
        return bool(self.leftovers or self.deletes or self.writes)


type _Rendered = RenderedFile | RenderedLink
# A verdict is what a sync does at one path: a verb, nothing (``None``), or a conflict.
type _Verdict = Verb | SyncProblem | None

_OUTSIDE: Final = "resolves outside the hub"
_NO_LONGER_RENDERED: Final = "differs from its hub.lock entry and is no longer rendered"


def _bit(*, executable: bool) -> str:
    return "+x" if executable else "-x"


def _placement_problem(path: str, entries: Mapping[str, TreeEntry]) -> PathProblem | None:
    # Steps 1 and 2 of E5: before any equality, so a path equal only through a link is not clean.
    problem = _ancestor_problem(path, entries)
    if problem is None and isinstance(link := entries.get(path), LinkEntry) and link.outside:
        problem = _OUTSIDE
    return None if problem is None else PathProblem(path, problem)


def _equals_render(rendered: _Rendered, disk: TreeEntry) -> bool:
    if isinstance(rendered, RenderedLink):
        return isinstance(disk, LinkEntry) and disk.target == rendered.target
    return (
        isinstance(disk, FileEntry)
        and _content(disk, rendered.path) == rendered.content
        and disk.executable == rendered.executable
    )


def _equals_entry(entry: LockEntry, disk: TreeEntry, path: str) -> bool:
    if isinstance(entry, ManagedLinkEntry):
        return isinstance(disk, LinkEntry) and disk.target == entry.symlink
    if isinstance(entry, ManagedFileEntry) and isinstance(disk, FileEntry):
        digest = hashlib.sha256(_content(disk, path)).hexdigest()
        return digest == entry.sha256 and disk.executable == entry.executable
    return False


def _fits(rendered: _Rendered, disk: TreeEntry) -> bool:
    return isinstance(disk, LinkEntry if isinstance(rendered, RenderedLink) else FileEntry)


def _render_conflict(rendered: _Rendered, disk: TreeEntry) -> SyncProblem:
    """Why ``disk``, which differs from the render, is not replaced by it."""
    if isinstance(rendered, RenderedLink) and isinstance(disk, LinkEntry):
        cause = f"link target differs (on disk -> {disk.target}, render -> {rendered.target})"
        return PathProblem(rendered.path, cause)
    if isinstance(rendered, RenderedFile) and isinstance(disk, FileEntry):
        on_disk = _content(disk, rendered.path)
        if on_disk != rendered.content:
            return ContentConflict(path=rendered.path, on_disk=on_disk, render=rendered.content)
        on_disk_bit = _bit(executable=disk.executable)
        render_bit = _bit(executable=rendered.executable)
        cause = f"executable bit differs (on disk {on_disk_bit}, render {render_bit})"
        return PathProblem(rendered.path, cause)
    belongs = "link" if isinstance(rendered, RenderedLink) else "file"
    return PathProblem(rendered.path, _type_problem(disk, belongs=belongs))


def _managed_verdict(
    rendered: _Rendered, entry: LockEntry | None, entries: Mapping[str, TreeEntry]
) -> _Verdict:
    problem = _placement_problem(rendered.path, entries)
    disk = entries.get(rendered.path)
    if problem is not None or disk is None:
        # A path with no managed entry was never written by a sync: it is created, not restored.
        managed = isinstance(entry, ManagedFileEntry | ManagedLinkEntry)
        return problem or (Verb.RESTORED if managed else Verb.CREATED)
    if _equals_render(rendered, disk):
        return None
    # The type rules come first: a path whose rendered type changed is never replaced (Q-16).
    if _fits(rendered, disk) and entry is not None and _equals_entry(entry, disk, rendered.path):
        return Verb.UPDATED
    return _render_conflict(rendered, disk)


def _seeded_verdict(
    rendered: _Rendered, entry: LockEntry | None, entries: Mapping[str, TreeEntry]
) -> _Verdict:
    if entry is not None:
        # Seeded once (or managed before and seeded now): the project's, whatever is on disk.
        return None
    problem = _placement_problem(rendered.path, entries)
    disk = entries.get(rendered.path)
    if problem is not None or disk is None:
        return problem or Verb.CREATED
    return None if _fits(rendered, disk) else _render_conflict(rendered, disk)


def _rendered_verdict(
    rendered: _Rendered, entry: LockEntry | None, entries: Mapping[str, TreeEntry]
) -> _Verdict:
    if rendered.ownership is Ownership.SEEDED:
        return _seeded_verdict(rendered, entry, entries)
    return _managed_verdict(rendered, entry, entries)


def _unrendered_verdict(path: str, entry: LockEntry, entries: Mapping[str, TreeEntry]) -> _Verdict:
    """A lock entry the render no longer holds: dropped, deleted, or a conflict."""
    if isinstance(entry, SeededEntry) or path == HUB_JSON_PATH:
        return None
    problem = _placement_problem(path, entries)
    disk = entries.get(path)
    if problem is not None or disk is None:
        return problem
    if _equals_entry(entry, disk, path):
        return Verb.DELETED
    return PathProblem(path, _NO_LONGER_RENDERED)


def _leftovers(entries: Mapping[str, TreeEntry], planned: set[str]) -> tuple[str, ...]:
    # The reader lists only the planned folders, so a leftover here lies in one of them.
    ancestors = {ancestor for path in planned for ancestor in _ancestors(path)}
    return tuple(
        sorted(
            path
            for path, entry in entries.items()
            if path not in planned and path not in ancestors and _is_leftover(path, entry)
        )
    )


def _write(rendered: _Rendered) -> FileWrite | LinkWrite:
    if isinstance(rendered, RenderedLink):
        return LinkWrite(path=rendered.path, target=rendered.target)
    return FileWrite(path=rendered.path, content=rendered.content, executable=rendered.executable)


def _changes(verdicts: Mapping[str, _Verdict]) -> tuple[SyncChange, ...]:
    return tuple(
        SyncChange(path=path, verb=verdict)
        for path, verdict in sorted(verdicts.items())
        if isinstance(verdict, Verb)
    )


def _problems(verdicts: Iterable[_Verdict]) -> tuple[SyncProblem, ...]:
    found = [each for each in verdicts if isinstance(each, PathProblem | ContentConflict)]
    return tuple(sorted(found, key=lambda problem: problem.path))


def plan_sync(
    *,
    rendered: RenderedHub,
    config: HubConfig,
    lock: HubLock,
    lock_content: bytes,
    tree: TreeSnapshot,
) -> SyncPlan | SyncConflicts:
    """Plan a sync of the hub ``tree`` describes to ``rendered`` for ``config``.

    ``lock`` is the lock read back and ``lock_content`` its exact bytes: the new lock is written
    exactly when its bytes differ (spec Q-15). ``tree`` must hold the content of every rendered
    managed file and of every managed file ``lock`` records. Raises ``ValueError`` when the render
    holds ``hub.json`` or ``hub.lock``, or when a file it compares was read without its content.
    """
    _check_render(rendered)
    entries = tree.entries
    items: list[_Rendered] = [*rendered.files, *rendered.links]
    verdicts: dict[str, _Verdict] = {
        each.path: _rendered_verdict(each, lock.files.get(each.path), entries) for each in items
    }
    gone = {
        path: _unrendered_verdict(path, entry, entries)
        for path, entry in lock.files.items()
        if path not in verdicts
    }
    problems = _problems([*verdicts.values(), *gone.values()])
    if problems:
        return SyncConflicts(problems=problems)
    new_lock = build_hub_lock(rendered=rendered, config=config)
    new_bytes = lock_bytes(new_lock)
    # Files come before links in ``items``, each in path order: the write order of spec Q-13.
    writes: list[FileWrite | LinkWrite] = [
        _write(each) for each in items if isinstance(verdicts[each.path], Verb)
    ]
    written = [write.path for write in writes]
    lock_written = new_bytes != lock_content
    if lock_written:
        writes.append(FileWrite(path=HUB_LOCK_PATH, content=new_bytes, executable=False))
    planned = {*verdicts, *lock.files, HUB_JSON_PATH, HUB_LOCK_PATH}
    return SyncPlan(
        leftovers=_leftovers(entries, planned),
        deletes=tuple(sorted(path for path, verdict in gone.items() if verdict is Verb.DELETED)),
        folders=_missing_folders(written, entries),
        writes=tuple(writes),
        changes=_changes(verdicts | gone),
        lock=new_lock,
        lock_written=lock_written,
    )
