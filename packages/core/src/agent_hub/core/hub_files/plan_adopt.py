"""The adopt planner (ADR 0009, AGH-16): how ``hub sync --adopt`` joins a hand-made hub to the lock.

``plan_adopt`` takes what ``plan_sync`` takes, except that the hub may have no ``hub.lock`` yet.
A path the lock records follows plain sync's rule. A rendered path with no entry is settled when
adopt can decide it alone: equal to its render, it is recorded as managed; a managed path that is
absent, or a seeded one, is created; a seeded file present (whatever its bytes) is recorded. Every
other path is left as it is and out of the new lock, at its previous entry when it had one (spec
Q-4), and the settled paths are still applied. The plan names each such path in ``conflicts``
with sync's cause. It does no I/O; the generator's file adapter applies the plan, ``hub.lock`` last.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum

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
    _check_render,
    _missing_folders,
)
from agent_hub.core.hub_files.plan_sync import (
    SyncChange,
    SyncProblem,
    Verb,
    _changes,
    _leftovers,
    _name_clashes,
    _problems,
    _Rendered,
    _rendered_verdict,
    _unrendered_verdict,
    _Verdict,
    _write,
)
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.tree_snapshot import TreeEntry, TreeSnapshot

# The verbs a path is written with; ``RECORDED`` and ``MIGRATED`` paths are joined as they are.
_WRITTEN = frozenset({Verb.CREATED, Verb.RESTORED, Verb.UPDATED})


class ListedKind(StrEnum):
    """What differs at a listed path, which ``--accept`` may replace with its render."""

    CONTENT = "content"
    LINK = "link"
    MIGRATION = "migration"


@dataclass(frozen=True, kw_only=True, slots=True)
class Listed:
    """A path adopt leaves as it is until ``--accept`` names it, with both sides of the difference.

    ``CONTENT`` fills the bytes (``None`` on the side not read) and executable bits; ``LINK`` the
    two targets; ``MIGRATION`` the directory link's target and ``link_count``, the number of links
    rendered under it.
    """

    path: str
    kind: ListedKind
    on_disk: bytes | None = None
    render: bytes | None = None
    on_disk_executable: bool = False
    render_executable: bool = False
    on_disk_target: str | None = None
    render_target: str | None = None
    link_count: int = 0


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
    # Filled by the listing rules (AGH-16 plan tasks 1.2 and 1.3); empty until then.
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


def _adopt_verdict(
    rendered: _Rendered, entry: LockEntry | None, entries: Mapping[str, TreeEntry]
) -> _Verdict:
    verdict = _rendered_verdict(rendered, entry, entries)
    # With no entry, sync's "nothing to do" is a managed path equal to its render or a seeded file
    # present: adopt joins it to the lock as it is.
    return Verb.RECORDED if entry is None and verdict is None else verdict


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
    verdicts: dict[str, _Verdict] = {
        each.path: _adopt_verdict(each, old.get(each.path), entries) for each in items
    }
    gone = {
        path: _unrendered_verdict(path, entry, entries)
        for path, entry in old.items()
        if path not in verdicts
    }
    clashes = _name_clashes(rendered, project=config.project.name, extensions=extensions)
    conflicts = _problems([*verdicts.values(), *gone.values(), *clashes])
    unsettled = {each.path for each in conflicts}
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
    planned = {*verdicts, *old, HUB_JSON_PATH, HUB_LOCK_PATH}
    return AdoptPlan(
        leftovers=_leftovers(entries, planned),
        deletes=tuple(sorted(path for path, verdict in settled.items() if verdict is Verb.DELETED)),
        folders=_missing_folders(written, entries),
        writes=tuple(writes),
        changes=_changes(settled),
        lock=new_lock,
        lock_written=lock_written,
        listed=(),
        conflicts=conflicts,
    )
