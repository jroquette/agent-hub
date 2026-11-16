"""Seed units: seeded files written together or not at all (AGH-227).

A built-in workflow pack, ``workflows/<pack>/…``, is one unit. Init, sync and adopt seed it only
into a hub that never had it: the lock holds none of its paths, and its folder, if present, holds
nothing but the folders and files of the render with the render's bytes (what an interrupted seed
leaves, so the next run completes it). Else none of its files is written, so a later release never
drops a new fixture or prompt into a hub's own (stale or custom) pack, and a pack the hub deleted
stays deleted. The lock still records every rendered path: a skipped file is the project's, as a
deleted seeded file is. The tree readers read each pack file's bytes and list each pack folder.
"""

from collections.abc import Iterable, Mapping
from typing import Final

from agent_hub.core.hub_files.rendered_file import Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, TreeEntry
from agent_hub.core.workflows.catalog import HUB_WORKFLOWS_FOLDER

UNIT_ROOT: Final = HUB_WORKFLOWS_FOLDER


def seed_unit(path: str) -> str | None:
    """``workflows/<pack>`` for a path inside a pack, else ``None``."""
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 and parts[0] == UNIT_ROOT else None


def unit_files(rendered: RenderedHub) -> dict[str, RenderedFile]:
    """The rendered seeded files that lie in a seed unit, by path."""
    return {
        file.path: file
        for file in rendered.files
        if file.ownership is Ownership.SEEDED and seed_unit(file.path) is not None
    }


def unit_folders(rendered: RenderedHub) -> tuple[str, ...]:
    """Every folder of the render's seed units, the unit folders included, sorted."""
    found: set[str] = set()
    for path in unit_files(rendered):
        parts = path.split("/")
        found.update("/".join(parts[:end]) for end in range(2, len(parts)))
    return tuple(sorted(found))


def held_units(
    rendered: RenderedHub, entries: Mapping[str, TreeEntry], locked: Iterable[str]
) -> frozenset[str]:
    """The rendered seed units the hub already has: in its lock, or on disk as its own."""
    files = unit_files(rendered)
    folders = set(unit_folders(rendered))
    units = {seed_unit(path) for path in files}
    held = {seed_unit(path) for path in locked} & units
    for path, entry in entries.items():
        unit = seed_unit(path)
        if unit in units and not _is_render(path, entry, files=files, folders=folders):
            held.add(unit)
    return frozenset(unit for unit in held if unit is not None)


def is_held(path: str, held: frozenset[str]) -> bool:
    """Whether ``path`` lies in a unit the hub already has, so it is never written."""
    unit = seed_unit(path)
    return unit is not None and unit in held


def _is_render(
    path: str, entry: TreeEntry, *, files: Mapping[str, RenderedFile], folders: set[str]
) -> bool:
    if isinstance(entry, FolderEntry):
        return path in folders
    file = files.get(path)
    return (
        file is not None
        and isinstance(entry, FileEntry)
        and entry.content == file.content
        and entry.executable == file.executable
    )
