"""Read a hub's ``brain/`` for the brain browser and the learnings (AGH-201, S8, L7).

Nothing outside ``<hub>/brain`` is ever opened, and no link is followed: each folder on the way
is opened relative to its parent with ``O_NOFOLLOW`` (as ``feature_files`` does), so a linked
folder or note is refused, and a note is read only when ``fstat`` says it is a regular file.
A path is first checked by core's ``brain_relative`` (no ``..``, no absolute path, no hidden
segment, ``.md`` only, never ``auto/``); a path it refuses reads as missing, so ``auto/`` is
never told apart from an absent note.

The listing is bounded: at most ``MAX_BRAIN_FILES`` notes, ``MAX_BRAIN_FOLDERS`` folders and
``MAX_BRAIN_DEPTH`` folder levels below ``brain/``, walked in name order; hidden names and the
top-level ``auto/`` (in any case) are skipped. An unreadable folder, a name that is not UTF-8, or
a note or folder left out by a cap, is counted in ``skipped``; a cap also sets ``truncated``.
Whatever the caps keep, the walk examines at most ``MAX_BRAIN_ENTRIES_EXAMINED`` names in all
(each folder is read as it is scanned, never all at once); past that it stops and sets
``truncated``. ``brain_folders`` names the top-level folders only, under the same budget.
"""

import contextlib
import errno
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agent_hub.core.brain.brain_note import BrainEntry
from agent_hub.core.brain.brain_path import (
    BRAIN_FOLDER,
    NOTE_SUFFIX,
    BrainPathError,
    brain_relative,
    is_personal_folder,
)
from agent_hub.core.hubs.hub_registry import BrainListing, UnreadHubFile

MAX_BRAIN_FILES: Final = 2_000
MAX_BRAIN_FOLDERS: Final = 500
MAX_BRAIN_DEPTH: Final = 8
# Names read from folders by one walk, kept or not (hidden, auto/, other files, left out by a cap).
MAX_BRAIN_ENTRIES_EXAMINED: Final = 10_000
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_CHUNK: Final = 65_536
# One line each; never a path, so a message cannot reveal where a link points.
_MISSING: Final = UnreadHubFile(
    message="cannot read: no such note", is_missing=True, kind="missing"
)
_NOT_REGULAR: Final = UnreadHubFile(
    message="cannot read: not a regular file", is_missing=False, kind="not_regular"
)


@dataclass(kw_only=True, slots=True)
class _Walk:
    entries: list[BrainEntry] = field(default_factory=list)
    folders: int = 0
    skipped: int = 0
    examined: int = 0
    truncated: bool = False

    @property
    def spent(self) -> bool:
        return self.examined >= MAX_BRAIN_ENTRIES_EXAMINED

    def cap(self, left_out: int = 1) -> None:
        self.truncated = True
        self.skipped += left_out


def list_brain(hub_root: Path) -> BrainListing:
    """The ``.md`` notes under ``<hub_root>/brain``, sorted by path; none when it is absent."""
    walk = _Walk()
    try:
        with _opened_folders(hub_root, ()) as brain:
            _walk(brain, (), walk)
    except OSError:
        return BrainListing(entries=())
    entries = sorted(walk.entries, key=lambda entry: entry.path)
    return BrainListing(entries=tuple(entries), truncated=walk.truncated, skipped=walk.skipped)


def brain_folders(hub_root: Path) -> tuple[str, ...]:
    """The folders directly under ``<hub_root>/brain`` by name (no hidden name, no ``auto/``, no
    link), at most ``MAX_BRAIN_ENTRIES_EXAMINED`` names read; none when it is absent."""
    walk = _Walk()
    folders: list[str] = []
    try:
        with _opened_folders(hub_root, ()) as brain:
            for name in _listed(brain, (), walk):
                with contextlib.suppress(OSError):
                    if stat.S_ISDIR(os.stat(name, dir_fd=brain, follow_symlinks=False).st_mode):
                        folders.append(name)
    except OSError:
        return ()
    return tuple(folders)


def read_brain_file(hub_root: Path, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
    """The bytes of ``brain/<path>`` when it is a regular file of at most ``max_bytes``, or why
    not (``missing``, ``not_regular``, ``too_large`` or ``unreadable``)."""
    try:
        folders, name = _split(path)
    except BrainPathError:
        return _MISSING
    try:
        with _opened_folders(hub_root, folders) as folder:
            descriptor = os.open(name, _FILE_FLAGS, dir_fd=folder)
    except OSError as error:
        return _unread(error)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            return _NOT_REGULAR
        if status.st_size > max_bytes:
            return _too_large(max_bytes)
        content = _read_at_most(descriptor, max_bytes + 1)
    except OSError as error:
        return _unread(error)
    finally:
        os.close(descriptor)
    return _too_large(max_bytes) if len(content) > max_bytes else content


def brain_file_size(hub_root: Path, path: str) -> int | None:
    """The size of the regular file ``brain/<path>``; None when absent, a link or unreadable."""
    try:
        folders, name = _split(path)
    except BrainPathError:
        return None
    try:
        with _opened_folders(hub_root, folders) as folder:
            status = os.stat(name, dir_fd=folder, follow_symlinks=False)
    except OSError:
        return None
    return status.st_size if stat.S_ISREG(status.st_mode) else None


def _split(path: str) -> tuple[tuple[str, ...], str]:
    parts = brain_relative(path).parts
    return parts[:-1], parts[-1]


@contextlib.contextmanager
def _opened_folders(hub_root: Path, folders: tuple[str, ...]) -> Iterator[int]:
    """The descriptor of ``brain/<folders>``, each level opened without following a link."""
    opened: list[int] = []
    try:
        parent = os.open(hub_root, os.O_RDONLY | os.O_DIRECTORY)
        opened.append(parent)
        for name in (BRAIN_FOLDER, *folders):
            parent = _open_folder(name, parent)
            opened.append(parent)
        yield parent
    finally:
        for descriptor in opened:
            os.close(descriptor)


def _open_folder(name: str, parent: int) -> int:
    """``name`` opened as a folder under ``parent``; a link raises ``ELOOP`` on every system
    (Linux says ``ENOTDIR`` for a linked folder opened with ``O_DIRECTORY | O_NOFOLLOW``)."""
    try:
        return os.open(name, _FOLDER_FLAGS, dir_fd=parent)
    except NotADirectoryError:
        if stat.S_ISLNK(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
            raise OSError(errno.ELOOP, "a link") from None
        raise


def _listed(folder: int, at: tuple[str, ...], walk: _Walk) -> list[str]:
    """The names in ``folder`` worth a look, sorted: read until the walk's budget is spent
    (then ``truncated``); hidden names and the top-level ``auto/`` dropped, a name that is not
    UTF-8 counted in ``skipped``."""
    names: list[str] = []
    with os.scandir(folder) as found:
        for entry in found:
            if walk.spent:
                walk.truncated = True
                break
            walk.examined += 1
            name = entry.name
            if name.startswith(".") or (not at and is_personal_folder(name)):
                continue
            try:
                name.encode()
            except UnicodeEncodeError:
                walk.skipped += 1
                continue
            names.append(name)
    return sorted(names)


def _walk(folder: int, at: tuple[str, ...], walk: _Walk) -> None:
    subfolders: list[str] = []
    for name in _listed(folder, at, walk):
        try:
            status = os.stat(name, dir_fd=folder, follow_symlinks=False)
        except OSError:
            walk.skipped += 1
            continue
        if stat.S_ISDIR(status.st_mode):
            subfolders.append(name)
        elif stat.S_ISREG(status.st_mode) and name.endswith(NOTE_SUFFIX):
            if len(walk.entries) >= MAX_BRAIN_FILES:
                walk.cap()
                continue
            walk.entries.append(BrainEntry(path="/".join((*at, name)), size=status.st_size))
    for name in subfolders:
        if walk.spent:
            walk.truncated = True
            return
        _descend(folder, (*at, name), walk)


def _descend(parent: int, at: tuple[str, ...], walk: _Walk) -> None:
    if len(at) > MAX_BRAIN_DEPTH or walk.folders >= MAX_BRAIN_FOLDERS:
        walk.cap()
        return
    walk.folders += 1
    try:
        folder = os.open(at[-1], _FOLDER_FLAGS, dir_fd=parent)
    except OSError:
        walk.skipped += 1
        return
    try:
        _walk(folder, at, walk)
    except OSError:
        walk.skipped += 1
    finally:
        os.close(folder)


def _read_at_most(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    left = limit
    while left > 0:
        chunk = os.read(descriptor, min(left, _CHUNK))
        if not chunk:
            break
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def _too_large(max_bytes: int) -> UnreadHubFile:
    return UnreadHubFile(
        message=f"cannot read: larger than {max_bytes} bytes", is_missing=False, kind="too_large"
    )


def _unread(error: OSError) -> UnreadHubFile:
    if error.errno in {errno.ENOENT, errno.ENOTDIR}:
        return _MISSING
    if error.errno == errno.ELOOP:
        # O_NOFOLLOW met a link on the way: never followed.
        return _NOT_REGULAR
    return UnreadHubFile(
        message=f"cannot read: {error.strerror or type(error).__name__}",
        is_missing=False,
        kind="unreadable",
    )
