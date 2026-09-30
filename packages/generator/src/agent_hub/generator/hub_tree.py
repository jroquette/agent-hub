"""Read what a hub's target folder holds, without following a link (spec D2, E15).

The walk goes from the root one folder at a time through directory descriptors: each folder is
opened with ``O_DIRECTORY | O_NOFOLLOW`` relative to its parent's descriptor, listed with
``os.scandir(fd)``, and every entry is looked at with ``dir_fd`` and ``follow_symlinks=False``. So
the walk never descends into a symlink (nothing under a symlinked folder is listed: the init planner
finds a symlinked ancestor from the entries alone), a folder swapped for a link before it is opened
fails the open, and one swapped after only moves where the held folder is: nothing is ever read
through a link. A link records its target as written and whether its real path leaves the root.
Only the regular files the render wants are opened, with ``O_NOFOLLOW | O_NONBLOCK``, and a FIFO,
socket or device is never opened. The root's ``.git`` is not listed; only its presence is recorded.
Every ``OSError`` of the walk becomes a ``GeneratorError`` naming the path.
"""

import os
import stat
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeEntry,
    TreeSnapshot,
)
from agent_hub.generator.errors import GeneratorError

_GIT: Final = ".git"
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
# O_NOFOLLOW: a file swapped for a link since the listing is refused, not followed.
# O_NONBLOCK: one swapped for a FIFO cannot block the open; fstat then says what it is.
_FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


@dataclass(frozen=True)
class _Walk:
    real_root: str
    wanted: Collection[str]
    entries: dict[str, TreeEntry]


def read_hub_tree(root: Path, *, wanted: Collection[str]) -> TreeSnapshot:
    """Return every entry under ``root`` by relative POSIX path; ``root`` is already a real path.

    An absent root gives an empty snapshot. Raises ``GeneratorError`` when the root is not a
    folder, or naming the path when anything under it cannot be looked at or read.
    """
    shown = os.fspath(root)
    try:
        mode = os.lstat(root).st_mode
    except FileNotFoundError:
        return TreeSnapshot(entries={}, git_present=False)
    except OSError as error:
        raise _walk_error(shown, error) from error
    if not stat.S_ISDIR(mode):
        msg = f"{shown}: not a folder"
        raise GeneratorError(msg)
    walk = _Walk(real_root=os.path.realpath(root), wanted=wanted, entries={})
    root_fd = _open_folder(shown, None, path=shown)
    try:
        names = _list(root_fd, path=shown)
        git_present = _GIT in names
        _read_folder(root_fd, [name for name in names if name != _GIT], prefix="", walk=walk)
    finally:
        os.close(root_fd)
    return TreeSnapshot(
        entries={path: walk.entries[path] for path in sorted(walk.entries)},
        git_present=git_present,
    )


def _read_folder(folder_fd: int, names: list[str], *, prefix: str, walk: _Walk) -> None:
    for name in names:
        path = prefix + name
        entry = _entry(folder_fd, name, path=path, walk=walk)
        walk.entries[path] = entry
        if isinstance(entry, FolderEntry):
            child_fd = _open_folder(name, folder_fd, path=path)
            try:
                _read_folder(child_fd, _list(child_fd, path=path), prefix=path + "/", walk=walk)
            finally:
                os.close(child_fd)


def _open_folder(name: str, parent_fd: int | None, *, path: str) -> int:
    # A folder swapped for a link fails here: ELOOP (macOS) or ENOTDIR (Linux, with O_DIRECTORY).
    try:
        return os.open(name, _FOLDER_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        raise _walk_error(path, error) from error


def _list(folder_fd: int, *, path: str) -> list[str]:
    try:
        with os.scandir(folder_fd) as found:
            return [item.name for item in found]
    except OSError as error:
        raise _walk_error(path, error) from error


def _entry(folder_fd: int, name: str, *, path: str, walk: _Walk) -> TreeEntry:
    try:
        mode = os.stat(name, dir_fd=folder_fd, follow_symlinks=False).st_mode
        if stat.S_ISLNK(mode):
            target = os.readlink(name, dir_fd=folder_fd)
            # The walk never entered a link, so the link's folder is the same under the real root.
            resolved = os.path.realpath(os.path.join(walk.real_root, path))
            outside = os.path.commonpath([walk.real_root, resolved]) != walk.real_root
            return LinkEntry(target=target, outside=outside)
        if stat.S_ISDIR(mode):
            return FolderEntry()
        if not stat.S_ISREG(mode):
            return OtherEntry(kind=_other_kind(mode))
        executable = bool(mode & stat.S_IXUSR)
        if path not in walk.wanted:
            return FileEntry(executable=executable, content=None)
        return _read_file(folder_fd, name, executable=executable)
    except OSError as error:
        raise _walk_error(path, error) from error


def _read_file(folder_fd: int, name: str, *, executable: bool) -> TreeEntry:
    descriptor = os.open(name, _FILE_FLAGS, dir_fd=folder_fd)
    with open(descriptor, "rb") as opened:
        mode = os.fstat(opened.fileno()).st_mode
        if not stat.S_ISREG(mode):
            return OtherEntry(kind=_other_kind(mode))
        return FileEntry(executable=executable, content=opened.read())


def _walk_error(path: str, error: OSError) -> GeneratorError:
    return GeneratorError(f"{path}: {error.strerror or error}")


def _other_kind(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        return "device"
    return "unknown"
