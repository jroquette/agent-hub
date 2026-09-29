"""Read what a hub's target folder holds, without following a link (spec D2).

The walk never descends into a symlink, so nothing under a symlinked folder is listed: the init
planner finds a symlinked ancestor from the entries alone. A link records its target as written and
whether its real path leaves the root. Only the regular files the render wants are opened, with
``O_NOFOLLOW | O_NONBLOCK``, and a FIFO, socket or device is never opened. The root's ``.git`` is
not listed; only its presence is recorded.
"""

import os
import stat
from collections.abc import Collection
from pathlib import Path

from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeEntry,
    TreeSnapshot,
)
from agent_hub.generator.errors import GeneratorError

_GIT = ".git"


def read_hub_tree(root: Path, *, wanted: Collection[str]) -> TreeSnapshot:
    """Return every entry under ``root`` by relative POSIX path; ``root`` is already a real path.

    An absent root gives an empty snapshot. Raises ``GeneratorError`` when the root is not a
    folder, or naming the path when a wanted file cannot be read.
    """
    if not os.path.lexists(root):
        return TreeSnapshot(entries={}, git_present=False)
    if not stat.S_ISDIR(os.lstat(root).st_mode):
        msg = f"{root}: not a folder"
        raise GeneratorError(msg)
    real_root = os.path.realpath(root)
    entries: dict[str, TreeEntry] = {}
    folders = [("", os.fspath(root))]
    while folders:
        prefix, folder = folders.pop()
        with os.scandir(folder) as found:
            for item in found:
                if not prefix and item.name == _GIT:
                    continue
                path = prefix + item.name
                entry = _entry(item, path=path, real_root=real_root, wanted=wanted)
                entries[path] = entry
                if isinstance(entry, FolderEntry):
                    folders.append((path + "/", item.path))
    return TreeSnapshot(
        entries={path: entries[path] for path in sorted(entries)},
        git_present=os.path.lexists(os.path.join(root, _GIT)),
    )


def _entry(
    item: os.DirEntry[str], *, path: str, real_root: str, wanted: Collection[str]
) -> TreeEntry:
    mode = item.stat(follow_symlinks=False).st_mode
    if stat.S_ISLNK(mode):
        return _link(item.path, real_root=real_root)
    if stat.S_ISDIR(mode):
        return FolderEntry()
    if not stat.S_ISREG(mode):
        return OtherEntry(kind=_other_kind(mode))
    executable = bool(mode & stat.S_IXUSR)
    if path not in wanted:
        return FileEntry(executable=executable, content=None)
    return _read_file(item.path, path=path, executable=executable)


def _link(link: str, *, real_root: str) -> LinkEntry:
    resolved = os.path.realpath(link)
    return LinkEntry(
        target=os.readlink(link),
        outside=os.path.commonpath([real_root, resolved]) != real_root,
    )


def _read_file(file: str, *, path: str, executable: bool) -> TreeEntry:
    # O_NOFOLLOW: a file swapped for a link since the listing is refused, not followed.
    # O_NONBLOCK: one swapped for a FIFO cannot block the open; fstat then says what it is.
    try:
        descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with open(descriptor, "rb") as opened:
            mode = os.fstat(opened.fileno()).st_mode
            if not stat.S_ISREG(mode):
                return OtherEntry(kind=_other_kind(mode))
            content = opened.read()
    except OSError as error:
        msg = f"{path}: {error.strerror}"
        raise GeneratorError(msg) from error
    return FileEntry(executable=executable, content=content)


def _other_kind(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        return "device"
    return "unknown"
