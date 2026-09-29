"""Write an init plan into a hub folder through temp files (spec D2, Q-5, Q-6).

The root is opened once per call. Its real path is taken before the open and checked against the
opened folder (device and inode), so the path the link check reads names the folder written to.
Every path is reached from that descriptor one folder at a time through directory descriptors
opened with ``O_DIRECTORY | O_NOFOLLOW``, so a folder swapped for a symlink is refused when the
descent meets it (``SymlinkedAncestorError``), and a swap after the descent (the root's too) only
moves where the held folder is: nothing is ever written through a link. A file is written to
``.<name>.hub-tmp-<8 hex>`` in its final folder, created with ``O_CREAT | O_EXCL | O_NOFOLLOW`` at
mode 0o600, given its final mode (``0o777`` or ``0o666`` less the umask) and then ``os.replace``d
onto its name; a link is made at the temp name and replaced the same way. On an error the temp
entry this write created is removed, never one it found there (a removal that fails is a note on
the write's error, never masking it). No ``fsync`` (Q-6).

Every path is checked before anything is touched: it must be relative, with no empty, ``.`` or
``..`` segment, because ``openat`` with ``O_NOFOLLOW`` still climbs out of the root through ``..``,
and no NUL byte.
A path that is not is a caller bug (``ValueError``); the planner only makes plain paths.
"""

import contextlib
import errno
import os
import stat
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.core.hub_files.plan_init import FileWrite, LinkWrite
from agent_hub.core.hub_files.tree_snapshot import is_leftover_name, temp_name
from agent_hub.generator.errors import (
    FileWriteError,
    LinkOutsideHubError,
    SymlinkedAncestorError,
)

_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_TEMP_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
_TEMP_MODE: Final = 0o600
_NOT_LEFTOVER: Final = "not a leftover file or link"
_ROOT_MOVED: Final = "the hub folder moved"
_NOT_UNDER_ROOT: Final = "not a relative path inside the hub"
_NOT_PLAIN_SEGMENTS: Final = frozenset({"", ".", ".."})


@dataclass(frozen=True)
class _Root:
    """The hub root, opened once: its descriptor, and the real path it had when opened."""

    fd: int
    real_path: str


def ensure_root(root: Path) -> None:
    """Create ``root`` and its parents when absent; call it only after the plan passed."""
    try:
        os.makedirs(root, exist_ok=True)
    except OSError as error:
        raise FileWriteError(path=os.fspath(root), cause=_cause(error)) from error


def remove_leftovers(root: Path, paths: Iterable[str]) -> None:
    """Remove each leftover temp file or link at ``paths``, never what a link points to.

    Raises ``ValueError`` for a path that is not plain and relative or whose name lacks the temp
    shape (a caller bug), and ``FileWriteError`` when the entry is no longer a regular file or a
    link.
    """
    listed = list(paths)
    for path in listed:
        _check_plain(path)
        if not is_leftover_name(_split(path)[1]):
            msg = f"{path}: not a leftover name"
            raise ValueError(msg)
    if not listed:
        # Nothing to remove: the root may not exist yet.
        return
    with _opened_root(root) as hub:
        for path in listed:
            folder, name = _split(path)
            with _folder(hub, path=path, folder=folder) as folder_fd:
                _remove_leftover(folder_fd, path=path, name=name)


def apply_writes(
    root: Path, *, folders: Iterable[str], writes: Iterable[FileWrite | LinkWrite]
) -> None:
    """Make ``folders`` (parents first), then apply ``writes`` in order under ``root``.

    Raises ``ValueError``, before anything is written, for a path that is not plain and relative.
    """
    folders = list(folders)
    writes = list(writes)
    for path in [*folders, *(write.path for write in writes)]:
        _check_plain(path)
    # ``os`` has no umask getter: set it and put it back, once per apply (Q-6's git rule).
    umask = os.umask(0o022)
    os.umask(umask)
    with _opened_root(root) as hub:
        for path in folders:
            parent, name = _split(path)
            with _folder(hub, path=path, folder=parent) as parent_fd:
                _make_folder(parent_fd, name=name, path=path)
        for write in writes:
            folder, name = _split(write.path)
            # The descent comes first, so a symlinked ancestor is named as such.
            with _folder(hub, path=write.path, folder=folder) as folder_fd:
                if isinstance(write, FileWrite):
                    mode = (0o777 if write.executable else 0o666) & ~umask
                    _write_file(folder_fd, name=name, write=write, mode=mode)
                else:
                    _check_inside(hub, write)
                    _write_link(folder_fd, name=name, write=write)


def _check_plain(path: str) -> None:
    # An absolute path starts with an empty segment, and an empty path is one. A NUL is refused
    # here too: the OS would refuse it only when the write reaches it, after earlier writes.
    if "\x00" in path or not _NOT_PLAIN_SEGMENTS.isdisjoint(path.split("/")):
        msg = f"{path!r}: {_NOT_UNDER_ROOT}"
        raise ValueError(msg)


def _split(path: str) -> tuple[str, str]:
    folder, _, name = path.rpartition("/")
    return folder, name


@contextlib.contextmanager
def _opened_root(root: Path) -> Iterator[_Root]:
    """Open ``root`` once; its real path, taken first, must still name the opened folder."""
    shown = os.fspath(root)
    real_path = os.path.realpath(root)
    try:
        descriptor = os.open(root, _FOLDER_FLAGS)
    except OSError as error:
        raise FileWriteError(path=shown, cause=_cause(error)) from error
    try:
        hub = _Root(fd=descriptor, real_path=real_path)
        _check_root(hub, path=shown)
        yield hub
    finally:
        os.close(descriptor)


def _check_root(hub: _Root, *, path: str) -> None:
    """Raise when ``hub.real_path`` no longer names the folder ``hub.fd`` holds."""
    held = os.fstat(hub.fd)
    try:
        named = os.stat(hub.real_path)
    except OSError as error:
        raise FileWriteError(path=path, cause=_ROOT_MOVED) from error
    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
        raise FileWriteError(path=path, cause=_ROOT_MOVED)


@contextlib.contextmanager
def _folder(hub: _Root, *, path: str, folder: str) -> Iterator[int]:
    """Yield a descriptor of ``folder`` under the held root, reached without following links."""
    descriptor = os.dup(hub.fd)
    try:
        segments = folder.split("/") if folder else []
        for depth, segment in enumerate(segments, start=1):
            child = _open_child(descriptor, segment, path=path, ancestor="/".join(segments[:depth]))
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _open_child(parent_fd: int, segment: str, *, path: str, ancestor: str) -> int:
    try:
        return os.open(segment, _FOLDER_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        # A link fails the open with ELOOP (macOS) or ENOTDIR (Linux, with O_DIRECTORY).
        if error.errno in {errno.ELOOP, errno.ENOTDIR} and _is_link(parent_fd, segment):
            raise SymlinkedAncestorError(path=path, ancestor=ancestor) from error
        raise FileWriteError(path=path, cause=_cause(error)) from error


def _is_link(folder_fd: int, name: str) -> bool:
    try:
        return stat.S_ISLNK(os.stat(name, dir_fd=folder_fd, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _check_inside(hub: _Root, write: LinkWrite) -> None:
    # The check resolves by path: first make sure the path still names the folder written to.
    _check_root(hub, path=write.path)
    real_root = hub.real_path
    folder, _ = _split(write.path)
    resolved = os.path.realpath(os.path.join(real_root, folder, write.target))
    if os.path.commonpath([real_root, resolved]) != real_root:
        raise LinkOutsideHubError(path=write.path)


def _write_file(folder_fd: int, *, name: str, write: FileWrite, mode: int) -> None:
    temp = temp_name(name, os.urandom(4).hex())
    created = False
    try:
        descriptor = os.open(temp, _TEMP_FLAGS, _TEMP_MODE, dir_fd=folder_fd)
        created = True
        with open(descriptor, "wb") as file:
            file.write(write.content)
            os.fchmod(file.fileno(), mode)
        os.replace(temp, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
    except OSError as error:
        raise _write_error(
            error, folder_fd, path=write.path, temp=temp if created else None
        ) from error


def _write_link(folder_fd: int, *, name: str, write: LinkWrite) -> None:
    temp = temp_name(name, os.urandom(4).hex())
    created = False
    try:
        os.symlink(write.target, temp, dir_fd=folder_fd)
        created = True
        os.replace(temp, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
    except OSError as error:
        raise _write_error(
            error, folder_fd, path=write.path, temp=temp if created else None
        ) from error


def _make_folder(parent_fd: int, *, name: str, path: str) -> None:
    try:
        os.mkdir(name, dir_fd=parent_fd)
    except OSError as error:
        raise FileWriteError(path=path, cause=_cause(error)) from error


def _remove_leftover(folder_fd: int, *, path: str, name: str) -> None:
    try:
        mode = os.stat(name, dir_fd=folder_fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise FileWriteError(path=path, cause=_cause(error)) from error
    if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
        raise FileWriteError(path=path, cause=_NOT_LEFTOVER)
    try:
        # ``unlink`` on a link removes the link itself, wherever it points.
        os.unlink(name, dir_fd=folder_fd)
    except OSError as error:
        raise FileWriteError(path=path, cause=_cause(error)) from error


def _write_error(error: OSError, folder_fd: int, *, path: str, temp: str | None) -> FileWriteError:
    """The ``FileWriteError`` for ``error``, once the temp entry this write created is removed.

    The write's own failure is the one reported: a temp entry that cannot be removed is a note
    naming it (the next init lists it as a leftover), never an error that masks the first.
    """
    failure = FileWriteError(path=path, cause=_cause(error))
    if temp is not None:
        try:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp, dir_fd=folder_fd)
        except OSError as cleanup:
            folder, _ = _split(path)
            left = f"{folder}/{temp}" if folder else temp
            failure.add_note(f"{left}: not removed: {_cause(cleanup)}")
    return failure


def _cause(error: OSError) -> str:
    return error.strerror or str(error)
