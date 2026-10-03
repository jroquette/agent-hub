"""The adopt planner (ADR 0009, AGH-16): how ``hub sync --adopt`` joins a hand-made hub to the lock.

``plan_adopt`` takes what ``plan_sync`` takes, except that the hub may have no ``hub.lock`` yet.
A path the lock records follows plain sync's rule. A rendered path with no entry is settled when
adopt can decide it alone: equal to its render, it is recorded as managed; a managed path that is
absent, or a seeded one, is created; a seeded file present (whatever its bytes) is recorded. A
managed path with no entry that has its rendered type and place but other bytes, executable bit
or link target is listed in ``listed``, with both sides. A directory link where a folder of
per-entry links is rendered (``.claude/skills``) is listed once as a migration, and the paths
under it get no verdict. Every other path (a type misfit, a symlinked ancestor that is not such a
link, a link resolving outside, a name in both plugins, a conflict of sync's rule) is named in
``conflicts`` with sync's cause. Listed and conflicting paths are left as they are and
out of the new lock, at their previous entry when they had one (spec Q-4), and the settled paths
are still applied. It does no I/O; the generator's file adapter applies the plan, ``hub.lock`` last.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, TypeIs

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.extension_inputs import ExtensionInputs
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    HubLock,
    LockEntry,
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
    _missing_folders,
)
from agent_hub.core.hub_files.plan_sync import (
    _OUTSIDE,
    SyncChange,
    SyncProblem,
    Verb,
    _changes,
    _leftovers,
    _name_clashes,
    _placement_problem,
    _problems,
    _Rendered,
    _rendered_verdict,
    _unrendered_verdict,
    _Verdict,
    _write,
)
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry, TreeSnapshot

# The verbs a path is written with; ``RECORDED`` and ``MIGRATED`` paths are joined as they are.
_WRITTEN = frozenset({Verb.CREATED, Verb.RESTORED, Verb.UPDATED})


class ListedKind(StrEnum):
    """What differs at a listed path, which ``--accept`` may replace with its render."""

    CONTENT = "content"
    LINK = "link"
    MIGRATION = "migration"


@dataclass(frozen=True, kw_only=True, slots=True)
class ContentDifference:
    """A managed file with no lock entry whose bytes or executable bit differ from its render."""

    kind: ClassVar[ListedKind] = ListedKind.CONTENT
    path: str
    on_disk: bytes
    render: bytes
    on_disk_executable: bool
    render_executable: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class LinkDifference:
    """A managed link with no lock entry whose target differs from its render's."""

    kind: ClassVar[ListedKind] = ListedKind.LINK
    path: str
    on_disk_target: str
    render_target: str


@dataclass(frozen=True, kw_only=True, slots=True)
class MigrationListing:
    """A directory link with no lock entry where a folder of per-entry links is rendered (E7).

    ``link_count`` is how many rendered links (base and project entries) the folder holds.
    """

    kind: ClassVar[ListedKind] = ListedKind.MIGRATION
    path: str
    on_disk_target: str
    link_count: int


# A path adopt leaves as it is until ``--accept`` names it, with both sides of the difference.
type Listed = ContentDifference | LinkDifference | MigrationListing


@dataclass(frozen=True, kw_only=True, slots=True)
class AdoptPlan:
    """What an adopt does, in the order the adapter applies it, and what it leaves as it is.

    The first seven fields mean what they mean in ``SyncPlan``; ``changes`` also holds the paths
    recorded as they are. ``lock`` records every settled path; a listed or conflicting path keeps
    its previous entry, or none. ``listed`` and ``conflicts`` are sorted by path.
    """

    leftovers: tuple[str, ...]
    deletes: tuple[str, ...]
    folders: tuple[str, ...]
    writes: tuple[FileWrite | LinkWrite, ...]
    changes: tuple[SyncChange, ...]
    lock: HubLock
    lock_written: bool
    listed: tuple[Listed, ...]
    conflicts: tuple[SyncProblem, ...]

    @property
    def pending(self) -> bool:
        """Whether applying the plan changes anything on disk."""
        return bool(self.leftovers or self.deletes or self.writes)

    @property
    def settled(self) -> bool:
        """Whether every path is joined to the lock: nothing listed, nothing conflicting."""
        return not (self.listed or self.conflicts)


# What adopt does at one path: sync's verdict, or a difference it lists.
type _AdoptVerdict = _Verdict | Listed


def _is_listed(verdict: _AdoptVerdict) -> TypeIs[Listed]:
    # The alias's own union, so a new kind of listing is covered with no second list to keep.
    return isinstance(verdict, Listed.__value__)


def _difference(rendered: _Rendered, disk: TreeEntry) -> Listed | None:
    """Both sides of a managed path that has its rendered type, or ``None`` when it has not."""
    if isinstance(rendered, RenderedLink):
        if not isinstance(disk, LinkEntry):
            return None
        return LinkDifference(
            path=rendered.path, on_disk_target=disk.target, render_target=rendered.target
        )
    if not isinstance(disk, FileEntry):
        return None
    return ContentDifference(
        path=rendered.path,
        on_disk=_content(disk, rendered.path),
        render=rendered.content,
        on_disk_executable=disk.executable,
        render_executable=rendered.executable,
    )


def _adopt_verdict(
    rendered: _Rendered, entry: LockEntry | None, entries: Mapping[str, TreeEntry]
) -> _AdoptVerdict:
    verdict = _rendered_verdict(rendered, entry, entries)
    if entry is not None or isinstance(verdict, Verb):
        return verdict
    # With no entry, sync's "nothing to do" is a managed path equal to its render or a seeded file
    # present: adopt joins it to the lock as it is.
    if verdict is None:
        return Verb.RECORDED
    # Sync's conflict for a managed path with no entry that differs where it fits: listed. A
    # misplaced path (symlinked ancestor, link resolving outside) or a type misfit, which has no
    # difference, stays a conflict.
    disk = entries.get(rendered.path)
    if (
        rendered.ownership is Ownership.MANAGED
        and disk is not None
        and _placement_problem(rendered.path, entries) is None
    ):
        return _difference(rendered, disk) or verdict
    return verdict


def _migrations(
    items: Collection[_Rendered], entries: Mapping[str, TreeEntry], old: Collection[str]
) -> dict[str, MigrationListing | PathProblem]:
    """E7: each directory link with no lock entry where a folder of per-entry links is rendered.

    A link holding a rendered file or nested links is not one: its paths keep sync's "symlinked
    ancestor" conflict. A migration link resolving outside the hub is a conflict at the link.
    """
    beneath: dict[str, list[_Rendered]] = {}
    for each in items:
        for ancestor in _ancestors(each.path):
            if isinstance(entries.get(ancestor), LinkEntry):
                beneath.setdefault(ancestor, []).append(each)
    found: dict[str, MigrationListing | PathProblem] = {}
    for path, held in sorted(beneath.items()):
        link = entries[path]
        per_entry = all(
            isinstance(each, RenderedLink) and each.path.rpartition("/")[0] == path for each in held
        )
        if not isinstance(link, LinkEntry) or path in old or not per_entry:
            continue
        if _ancestor_problem(path, entries) is not None:
            continue
        found[path] = (
            PathProblem(path, _OUTSIDE)
            if link.outside
            else MigrationListing(path=path, on_disk_target=link.target, link_count=len(held))
        )
    return found


def _settled_lock(
    rendered: RenderedHub,
    config: HubConfig,
    *,
    previous: HubLock | None,
    unsettled: Collection[str],
) -> HubLock:
    """The lock of ``rendered``, each unsettled path at its ``previous`` entry or left out."""
    built = build_hub_lock(rendered=rendered, config=config)
    old = {} if previous is None else previous.files
    files = {path: entry for path, entry in built.files.items() if path not in unsettled}
    files.update((path, old[path]) for path in unsettled if path in old)
    return built.model_copy(update={"files": dict(sorted(files.items()))})


def plan_adopt(
    *,
    rendered: RenderedHub,
    config: HubConfig,
    lock: HubLock | None,
    lock_content: bytes | None,
    tree: TreeSnapshot,
    extensions: ExtensionInputs,
) -> AdoptPlan:
    """Plan an adopt of the hub ``tree`` describes to ``rendered`` for ``config``.

    ``lock`` is the lock read back and ``lock_content`` its exact bytes, both ``None`` when the
    hub has no ``hub.lock``: the new lock is written when there was none or its bytes differ.
    ``tree`` and ``extensions`` are what ``plan_sync`` needs. Raises ``ValueError`` when the render
    holds ``hub.json`` or ``hub.lock``, or when a file it compares was read without its content.
    """
    _check_render(rendered)
    entries = tree.entries
    old = {} if lock is None else lock.files
    items: list[_Rendered] = [*rendered.files, *rendered.links]
    migrations = _migrations(items, entries, old)
    # The rendered paths under a migration get no verdict: the link stands for them all.
    under = {
        each.path
        for each in items
        if any(ancestor in migrations for ancestor in _ancestors(each.path))
    }
    every: dict[str, _AdoptVerdict] = {
        each.path: _adopt_verdict(each, old.get(each.path), entries)
        for each in items
        if each.path not in under
    }
    every.update(migrations)
    verdicts = {path: verdict for path, verdict in every.items() if not _is_listed(verdict)}
    gone = {
        path: _unrendered_verdict(path, entry, entries)
        for path, entry in old.items()
        if path not in every
    }
    clashes = _name_clashes(rendered, project=config.project.name, extensions=extensions)
    conflicts = _problems([*verdicts.values(), *gone.values(), *clashes])
    conflicting = {each.path for each in conflicts}
    # A listed path that also clashes is a conflict: ``--accept`` may not take it.
    listed = tuple(
        sorted(
            (each for each in every.values() if _is_listed(each) and each.path not in conflicting),
            key=lambda each: each.path,
        )
    )
    unsettled = conflicting | {each.path for each in listed} | under
    # A name clash leaves a path whose own verdict is a verb: only the settled verdicts count.
    settled = {
        path: verdict for path, verdict in (verdicts | gone).items() if path not in unsettled
    }
    new_lock = _settled_lock(rendered, config, previous=lock, unsettled=unsettled)
    new_bytes = lock_bytes(new_lock)
    # Files come before links in ``items``, each in path order: the write order of sync.
    writes: list[FileWrite | LinkWrite] = [
        _write(each) for each in items if settled.get(each.path) in _WRITTEN
    ]
    written = [write.path for write in writes]
    lock_written = new_bytes != lock_content
    if lock_written:
        writes.append(FileWrite(path=HUB_LOCK_PATH, content=new_bytes, executable=False))
    planned = {*every, *under, *old, HUB_JSON_PATH, HUB_LOCK_PATH}
    return AdoptPlan(
        leftovers=_leftovers(entries, planned),
        deletes=tuple(sorted(path for path, verdict in settled.items() if verdict is Verb.DELETED)),
        folders=_missing_folders(written, entries),
        writes=tuple(writes),
        changes=_changes(settled),
        lock=new_lock,
        lock_written=lock_written,
        listed=listed,
        conflicts=conflicts,
    )
