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

``hub sync`` reads less (spec Q-3, E2): ``read_root_entry`` looks at one name in the root, and
``read_planned_tree`` only at the paths it plans, the folders above them, and the leftover-shaped
names in their parent folders. The same descriptor rules hold, so unknown parts of the hub (notes,
run output, FIFOs, unreadable folders) are never opened, listed or looked at. Paths there must be
plain and relative (a ``ValueError`` before anything is read), since ``..`` climbs out even under
``O_NOFOLLOW``.

``hub doctor`` reads more (spec AC-11.3, E8): ``read_every_file`` walks as ``read_hub_tree``
does, reads every regular file, and leaves out nested repositories, as git would;
``list_every_file`` walks the same way and reads no file.
"""

import os
import stat
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeEntry,
    TreeSnapshot,
    is_leftover_name,
)
from agent_hub.generator.errors import GeneratorError

_GIT: Final = ".git"
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
# O_NOFOLLOW: a file swapped for a link since the listing is refused, not followed.
# O_NONBLOCK: one swapped for a FIFO cannot block the open; fstat then says what it is.
_FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_NOT_PLAIN_SEGMENTS: Final = frozenset({"", ".", ".."})
_NOT_UNDER_ROOT: Final = "not a relative path inside the hub"


@dataclass(frozen=True)
class _Walk:
    real_root: str
    # ``None``: every regular file is read.
    wanted: Collection[str] | None
    entries: dict[str, TreeEntry]
    # Leave out every folder below the root that holds a ``.git`` entry (a nested repository).
    skip_nested: bool = False


def read_hub_tree(root: Path, *, wanted: Collection[str]) -> TreeSnapshot:
    """Return every entry under ``root`` by relative POSIX path; ``root`` is already a real path.

    An absent root gives an empty snapshot. Raises ``GeneratorError`` when the root is not a
    folder, or naming the path when anything under it cannot be looked at or read.
    """
    return _walk_tree(root, wanted=wanted, skip_nested=False)


def read_every_file(root: Path) -> TreeSnapshot:
    """Return every entry under ``root`` as ``read_hub_tree`` does, each regular file read.

    Nested repositories are left out (spec E8): a folder below the root that holds a ``.git``
    entry, file or folder, is neither recorded nor descended, as git never lists one.
    """
    return _walk_tree(root, wanted=None, skip_nested=True)


def list_every_file(root: Path) -> TreeSnapshot:
    """Return every entry under ``root`` as ``read_every_file`` does, no file read.

    Each regular file is recorded with no content, so a file that cannot be read never fails
    the walk; a folder that cannot be listed still does.
    """
    return _walk_tree(root, wanted=(), skip_nested=True)


def _walk_tree(root: Path, *, wanted: Collection[str] | None, skip_nested: bool) -> TreeSnapshot:
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
    walk = _Walk(
        real_root=os.path.realpath(root), wanted=wanted, entries={}, skip_nested=skip_nested
    )
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


def read_root_entry(root: Path, name: str) -> TreeEntry | None:
    """Return the entry ``name`` in ``root`` without following it, or ``None`` when absent.

    Only a regular file is opened (its content read); a link, folder, FIFO, socket or device is
    returned as its entry. Raises ``ValueError`` when ``name`` is not one plain segment, and
    ``GeneratorError`` naming the path when the root or the entry cannot be read.
    """
    _check_plain(name)
    if "/" in name:
        msg = f"{name!r}: {_NOT_UNDER_ROOT}"
        raise ValueError(msg)
    shown = os.fspath(root)
    walk = _Walk(real_root=os.path.realpath(root), wanted={name}, entries={})
    root_fd = _open_folder(shown, None, path=shown)
    try:
        return _look(root_fd, name, path=name, walk=walk)
    finally:
        os.close(root_fd)


@dataclass(frozen=True)
class LinkFolder:
    """Where the entries of a listed folder are linked, and the entry type that is linked."""

    path: str
    linked: type[FileEntry] | type[FolderEntry]


@dataclass(frozen=True)
class _Descent:
    """The folders one planned read reached: open descriptors by path (``""`` is the root)."""

    walk: _Walk
    folders: dict[str, int]
    unreachable: set[str]


def read_planned_tree(
    root: Path,
    *,
    paths: Collection[str],
    wanted: Collection[str],
    listed: Collection[str] = (),
    links_in: Mapping[str, LinkFolder] = MappingProxyType({}),
) -> TreeSnapshot:
    """Return only what ``hub sync`` plans under ``root``; ``root`` is already a real path.

    For each of ``paths``: its ancestors down to the first that is not a folder, then the path
    itself when present (content read only when in ``wanted``). Each existing parent folder of a
    planned path, the root included, is listed, and only its leftover-shaped names are recorded.
    Each folder in ``listed`` is listed and every name in it recorded, never descended. For a
    listed folder that is a key of ``links_in``, each name found is also looked at (never listed)
    in the value folder, where its link would go (spec Q-20: one read for the project's entries
    and their link paths). Raises ``ValueError`` for a path that is not plain and relative, or a
    ``links_in`` key not in ``listed``, before anything is read, and ``GeneratorError`` naming the
    path when anything planned cannot be looked at or read.
    """
    _check_planned(paths, listed=listed, links_in=links_in)
    shown = os.fspath(root)
    descent = _Descent(
        walk=_Walk(real_root=os.path.realpath(root), wanted=wanted, entries={}),
        folders={"": _open_folder(shown, None, path=shown)},
        unreachable=set(),
    )
    try:
        root_names = _list(descent.folders[""], path=shown)
        for path in paths:
            folder, _, name = path.rpartition("/")
            folder_fd = _reach(folder, descent)
            if folder_fd is not None:
                _look(folder_fd, name, path=path, walk=descent.walk)
        parents = sorted({"", *(path.rpartition("/")[0] for path in paths)})
        for folder in parents:
            _record_names(folder, descent, names=root_names if not folder else None, every=False)
        for folder in listed:
            if _reach(folder, descent) is not None:
                _record_names(folder, descent, names=None, every=True)
        for folder, link_folder in links_in.items():
            names = _linkable_names(folder, linked=link_folder.linked, walk=descent.walk)
            _look_in(link_folder.path, names=names, descent=descent)
    finally:
        for folder_fd in descent.folders.values():
            os.close(folder_fd)
    entries = descent.walk.entries
    return TreeSnapshot(
        entries={path: entries[path] for path in sorted(entries)},
        git_present=_GIT in root_names,
    )


def _reach(folder: str, descent: _Descent) -> int | None:
    """The open descriptor of ``folder``, or ``None`` when it or an ancestor is not a folder."""
    if folder in descent.folders:
        return descent.folders[folder]
    if folder in descent.unreachable:
        return None
    parent, _, name = folder.rpartition("/")
    parent_fd = _reach(parent, descent)
    entry = None if parent_fd is None else _look(parent_fd, name, path=folder, walk=descent.walk)
    if parent_fd is None or not isinstance(entry, FolderEntry):
        # Nothing under a link, a file or an absent folder is ever looked at.
        descent.unreachable.add(folder)
        return None
    folder_fd = _open_folder(name, parent_fd, path=folder)
    descent.folders[folder] = folder_fd
    return folder_fd


def _check_planned(
    paths: Collection[str], *, listed: Collection[str], links_in: Mapping[str, LinkFolder]
) -> None:
    for path in [*paths, *listed, *(link_folder.path for link_folder in links_in.values())]:
        _check_plain(path)
    for folder in links_in:
        if folder not in listed:
            msg = f"{folder!r}: links_in names a folder that is not listed"
            raise ValueError(msg)


def _linkable_names(
    folder: str, *, linked: type[FileEntry] | type[FolderEntry], walk: _Walk
) -> list[str]:
    """The names right under ``folder`` whose entry is of type ``linked``, dotfiles never."""
    prefix = f"{folder}/"
    return [
        name
        for path, entry in walk.entries.items()
        if path.startswith(prefix) and isinstance(entry, linked)
        for name in [path.removeprefix(prefix)]
        if "/" not in name and not name.startswith(".")
    ]


def _look_in(folder: str, *, names: list[str], descent: _Descent) -> None:
    """Record each of ``names`` present in ``folder``, which is looked at by name, never listed.

    The names are only those a link is planned for (see ``_linkable_names``), so a dotfile or an
    entry of another type never makes the link folder be looked into.
    """
    folder_fd = _reach(folder, descent) if names else None
    if folder_fd is not None:
        for name in names:
            _look(folder_fd, name, path=f"{folder}/{name}", walk=descent.walk)


def _record_names(folder: str, descent: _Descent, *, names: list[str] | None, every: bool) -> None:
    folder_fd = descent.folders.get(folder)
    if folder_fd is None:
        return
    prefix = f"{folder}/" if folder else ""
    for name in _list(folder_fd, path=folder) if names is None else names:
        if name != _GIT and (every or is_leftover_name(name)):
            _look(folder_fd, name, path=prefix + name, walk=descent.walk)


def _look(folder_fd: int, name: str, *, path: str, walk: _Walk) -> TreeEntry | None:
    """Record and return the entry at ``path`` (``name`` in ``folder_fd``); ``None`` if absent."""
    if path in walk.entries:
        return walk.entries[path]
    try:
        mode = os.stat(name, dir_fd=folder_fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _walk_error(path, error) from error
    entry = _typed_entry(folder_fd, name, mode=mode, path=path, walk=walk)
    walk.entries[path] = entry
    return entry


def _check_plain(path: str) -> None:
    # An absolute path starts with an empty segment, and an empty path is one.
    if "\x00" in path or not _NOT_PLAIN_SEGMENTS.isdisjoint(path.split("/")):
        msg = f"{path!r}: {_NOT_UNDER_ROOT}"
        raise ValueError(msg)


def _read_folder(folder_fd: int, names: list[str], *, prefix: str, walk: _Walk) -> None:
    for name in names:
        path = prefix + name
        entry = _entry(folder_fd, name, path=path, walk=walk)
        walk.entries[path] = entry
        if isinstance(entry, FolderEntry):
            child_fd = _open_folder(name, folder_fd, path=path)
            try:
                child_names = _list(child_fd, path=path)
                if walk.skip_nested and _GIT in child_names:
                    del walk.entries[path]
                    continue
                _read_folder(child_fd, child_names, prefix=path + "/", walk=walk)
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
    except OSError as error:
        raise _walk_error(path, error) from error
    return _typed_entry(folder_fd, name, mode=mode, path=path, walk=walk)


def _typed_entry(folder_fd: int, name: str, *, mode: int, path: str, walk: _Walk) -> TreeEntry:
    try:
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
        if walk.wanted is not None and path not in walk.wanted:
            return FileEntry(executable=executable, content=None)
        return _read_file(folder_fd, name, executable=executable)
    except OSError as error:
        raise _walk_error(path, error) from error


def _read_file(folder_fd: int, name: str, *, executable: bool) -> TreeEntry:
    descriptor = os.open(name, _FILE_FLAGS, dir_fd=folder_fd)
    try:
        # Checked on the descriptor: the entry may have been swapped since it was looked at.
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISDIR(mode):
            return FolderEntry()
        if not stat.S_ISREG(mode):
            return OtherEntry(kind=_other_kind(mode))
        with open(descriptor, "rb", closefd=False) as opened:
            return FileEntry(executable=executable, content=opened.read())
    finally:
        os.close(descriptor)


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
