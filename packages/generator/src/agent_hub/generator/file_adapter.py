"""Write an init plan into a hub folder through temp files (spec D2, Q-5, Q-6).

Every path is reached from the root one folder at a time through directory descriptors opened with
``O_DIRECTORY | O_NOFOLLOW``, so a folder swapped for a symlink is refused when the descent meets it
(``SymlinkedAncestorError``), and a swap after the descent only moves where the held folder is:
nothing is ever written through a link. A file is written to ``.<name>.hub-tmp-<8 hex>`` in its
final folder, created with ``O_CREAT | O_EXCL | O_NOFOLLOW`` at mode 0o600, given its final mode
(``0o777`` or ``0o666`` less the umask) and then ``os.replace``d onto its name; a link is made at
the temp name and replaced the same way. On an error the temp entry is removed. No ``fsync`` (Q-6).
"""

import contextlib
import errno
import os
import stat
from collections.abc import Iterable, Iterator
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


def ensure_root(root: Path) -> None:
    """Create ``root`` and its parents when absent; call it only after the plan passed."""
    try:
        os.makedirs(root, exist_ok=True)
    except OSError as error:
        raise FileWriteError(path=os.fspath(root), cause=_cause(error)) from error


def remove_leftovers(root: Path, paths: Iterable[str]) -> None:
    """Remove each leftover temp file or link at ``paths``, never what a link points to.

    Raises ``ValueError`` for a path whose name lacks the temp shape (a caller bug), and
    ``FileWriteError`` when the entry is no longer a regular file or a link.
    """
    for path in paths:
        folder, name = _split(path)
        if not is_leftover_name(name):
            msg = f"{path}: not a leftover name"
            raise ValueError(msg)
        with _folder(root, path=path, folder=folder) as folder_fd:
            _remove_leftover(folder_fd, path=path, name=name)


def apply_writes(
    root: Path, *, folders: Iterable[str], writes: Iterable[FileWrite | LinkWrite]
) -> None:
    """Make ``folders`` (parents first), then apply ``writes`` in order under ``root``."""
    # ``os`` has no umask getter: set it and put it back, once per apply (Q-6's git rule).
    umask = os.umask(0o022)
    os.umask(umask)
    real_root = os.path.realpath(root)
    for path in folders:
        parent, name = _split(path)
        with _folder(root, path=path, folder=parent) as parent_fd:
            _make_folder(parent_fd, name=name, path=path)
    for write in writes:
        folder, name = _split(write.path)
        # The descent comes first, so a symlinked ancestor is named as such.
        with _folder(root, path=write.path, folder=folder) as folder_fd:
            if isinstance(write, FileWrite):
                mode = (0o777 if write.executable else 0o666) & ~umask
                _write_file(folder_fd, name=name, write=write, mode=mode)
            else:
                _check_inside(real_root, write)
                _write_link(folder_fd, name=name, write=write)


def _split(path: str) -> tuple[str, str]:
    folder, _, name = path.rpartition("/")
    return folder, name


@contextlib.contextmanager
def _folder(root: Path, *, path: str, folder: str) -> Iterator[int]:
    """Yield a descriptor of ``folder`` (relative to ``root``), reached without following links."""
    try:
        descriptor = os.open(root, _FOLDER_FLAGS)
    except OSError as error:
        raise FileWriteError(path=path, cause=_cause(error)) from error
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


def _check_inside(real_root: str, write: LinkWrite) -> None:
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
        if created:
            _discard(folder_fd, temp)
        raise FileWriteError(path=write.path, cause=_cause(error)) from error


def _write_link(folder_fd: int, *, name: str, write: LinkWrite) -> None:
    temp = temp_name(name, os.urandom(4).hex())
    created = False
    try:
        os.symlink(write.target, temp, dir_fd=folder_fd)
        created = True
        os.replace(temp, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
    except OSError as error:
        if created:
            _discard(folder_fd, temp)
        raise FileWriteError(path=write.path, cause=_cause(error)) from error


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


def _discard(folder_fd: int, temp: str) -> None:
    # Only a temp entry this write created is removed; the error being raised says what failed.
    with contextlib.suppress(FileNotFoundError):
        os.unlink(temp, dir_fd=folder_fd)


def _cause(error: OSError) -> str:
    return error.strerror or str(error)
