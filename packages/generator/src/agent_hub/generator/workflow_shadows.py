"""The hub workflows that override a built-in, for ``hub doctor``'s ``workflows.shadow``.

Discovery (``discover_workflows``) gives each built-in a hub workflow overrides; this module
pairs it with the hub's workflow of that name and compares the two packs. A pack is identical
when every file of the built-in's pack (hidden names and ``__pycache__`` skipped, as the seed
skips them) is a regular file of the hub's pack at the same path with the same bytes; the hub's
own extra files do not count. No link is followed: a link where the built-in has a file, or on
its path, differs. A hub file whose size is not the built-in file's differs unread, and each pair
of packs is compared once, however many workflows they hold. A built-in whose hub file did not
load is left out (``workflows.valid`` reports that file).
"""

import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from agent_hub.core.doctor.snapshot import WorkflowShadow
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows

# What the seed leaves out of a pack (``registry._pack_files``): hidden names and caches.
_SKIPPED_FOLDER: Final = "__pycache__"


def workflow_shadows(
    hub_root: Path, *, builtin_root: Path = BUILTIN_WORKFLOWS
) -> tuple[WorkflowShadow, ...]:
    """Each hub workflow that overrides a built-in, by name."""
    discovery = discover_workflows(hub_root, builtin_root=builtin_root)
    hub = {found.name: found for found in discovery.workflows if found.origin == "hub"}
    shadows: list[WorkflowShadow] = []
    compared: dict[tuple[Path, Path], bool] = {}
    for builtin in discovery.overridden:
        mine = hub.get(builtin.name)
        if mine is None:
            continue
        packs = (mine.pack_root, builtin.pack_root)
        if packs not in compared:
            compared[packs] = _holds_pack(*packs)
        shadows.append(
            WorkflowShadow(
                name=mine.name,
                path=mine.path.relative_to(hub_root).as_posix(),
                pack=mine.pack_root.relative_to(hub_root).as_posix(),
                builtin_pack=builtin.pack,
                identical=compared[packs],
            )
        )
    return tuple(shadows)


def _holds_pack(hub_pack: Path, builtin_pack: Path) -> bool:
    """Whether every file of ``builtin_pack`` is in ``hub_pack`` with the same bytes."""
    for relative in _pack_files(builtin_pack):
        theirs = builtin_pack / relative
        mine = _regular_bytes(hub_pack, relative, size=theirs.stat().st_size)
        if mine is None or mine != theirs.read_bytes():
            return False
    return True


def _pack_files(pack: Path) -> Iterator[str]:
    """The pack's regular files, relative and ``/``-separated; links are not followed."""
    for folder, folders, names in os.walk(pack):
        folders[:] = [name for name in folders if not _skipped(name)]
        below = Path(folder).relative_to(pack)
        for name in names:
            path = Path(folder) / name
            if not _skipped(name) and not path.is_symlink() and path.is_file():
                yield (below / name).as_posix()


def _skipped(name: str) -> bool:
    return name.startswith(".") or name == _SKIPPED_FOLDER


def _regular_bytes(root: Path, relative: str, *, size: int) -> bytes | None:
    """The bytes of ``root/relative`` when no part of its path is a link and it is a regular
    file of ``size`` bytes, the only case in which it is read; else ``None``."""
    path = root
    found: os.stat_result | None = None
    for part in relative.split("/"):
        path = path / part
        try:
            found = os.lstat(path)
        except OSError:
            return None
        if stat.S_ISLNK(found.st_mode):
            return None
    if found is None or not stat.S_ISREG(found.st_mode) or found.st_size != size:
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None
