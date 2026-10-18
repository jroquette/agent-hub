"""Read one versioned unit of a hub whole (AGH-295, S2, S8, D15, A1).

``read_unit`` reads a skill's folder, or an agent, hook or workflow file, into a ``UnitContent``,
or says why it cannot (``UnreadUnit``). The path is checked by core's ``unit_parts`` first: a
refused path (``settings.local.json`` among them) reads ``missing`` without touching the disk.
The hub is opened once; each folder on the way and inside a skill is opened relative to its
parent with ``O_DIRECTORY | O_NOFOLLOW``, so a linked folder is never entered; each file is
opened with ``O_NOFOLLOW | O_NONBLOCK`` (a FIFO never blocks) and its executable bit and size
come from ``fstat`` of the opened descriptor, so bit and bytes belong to one inode. A link, FIFO,
socket or device anywhere in the unit or on the way is ``unreadable``. A file over 256 KiB, more
than ``SKILL.md`` and 200 bundled files, a file deeper than 3 segments below the folder, or a
folder holding more names than a listing examines, is ``too_large``; every entry is counted
here, the listing's own budget is never trusted. A skill folder is walked stat-only first, and
one the walk already refuses (too many files, a special or oversized file) is refused before
any byte is read. Hidden names inside a skill folder are left
out, as the listing leaves them out. Nothing is written; no message names a path.
"""

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.core.hubs.hub_registry import UnreadUnit
from agent_hub.core.item_versions.item_units import unit_parts
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import MAX_UNIT_FILES, UnitContent, UnitFile
from agent_hub.core.skills.skill_sources import (
    DEFAULT_LIMITS,
    MAX_SKILL_FILE_BYTES,
    SKILL_FILE,
    SkillPathError,
)

_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY
_CHUNK: Final = 65_536
_MISSING: Final = UnreadUnit(kind="missing")
_TOO_LARGE: Final = UnreadUnit(kind="too_large")
_UNREADABLE: Final = UnreadUnit(kind="unreadable")


class _RefusedError(Exception):
    """The unit cannot be read whole: ``unread`` says why."""

    def __init__(self, unread: UnreadUnit) -> None:
        self.unread = unread
        super().__init__(unread.kind)


@dataclass(kw_only=True, slots=True)
class _Budget:
    """The names a folder walk may still look at."""

    names: int = DEFAULT_LIMITS.names_examined


def read_unit(hub_root: Path, unit_path: str, *, kind: UnitKind) -> UnitContent | UnreadUnit:
    """The unit at the hub-relative ``unit_path`` read whole, or why not."""
    try:
        parts = unit_parts(unit_path, kind)
    except SkillPathError:
        return _MISSING
    opened: list[int] = []
    try:
        parent = os.open(hub_root, os.O_RDONLY | os.O_DIRECTORY)
        opened.append(parent)
        for name in parts[:-1]:
            parent = _open_folder(name, parent)
            opened.append(parent)
        if kind is UnitKind.SKILL:
            return _folder_unit(parent, parts[-1])
        return UnitContent(files=(_read_file(parent, parts[-1], parts[-1]),))
    except _RefusedError as refused:
        return refused.unread
    except OSError as error:
        return _unread(error)
    finally:
        for descriptor in opened:
            os.close(descriptor)


def _folder_unit(parent: int, name: str) -> UnitContent | UnreadUnit:
    root = _open_folder(name, parent)
    try:
        # ``SKILL.md`` first: a folder without one is no skill, whatever else it holds.
        os.stat(SKILL_FILE, dir_fd=root, follow_symlinks=False)
        entries: list[_Entry] = []
        _walk(root, "", depth=1, entries=entries, budget=_Budget())
        ordered = sorted(entries, key=lambda entry: entry.path)
        _refuse_early(ordered)
        found = _read_in_order(root, ordered)
    finally:
        os.close(root)
    if not any(file.path == SKILL_FILE for file in found):
        return _MISSING
    return UnitContent(files=tuple(found))


@dataclass(frozen=True, slots=True)
class _Entry:
    """A name the walk found: its path in the unit, and why it cannot be read (None: a file)."""

    path: str
    problem: UnreadUnit | None


def _walk(folder: int, above: str, *, depth: int, entries: list[_Entry], budget: _Budget) -> None:
    """Every name below ``folder`` into ``entries``, stat-only; each path follows ``above`` (the
    folder's own path in the unit and a ``/``), ``depth`` segments below the skill's folder. A
    name that vanishes meanwhile is skipped, as the listing skips it."""
    for name in _names(folder, budget):
        path = f"{above}{name}"
        if depth > DEFAULT_LIMITS.skill_depth:
            entries.append(_Entry(path, _TOO_LARGE))
            return
        try:
            status = os.stat(name, dir_fd=folder, follow_symlinks=False)
        except FileNotFoundError, NotADirectoryError:
            continue
        if stat.S_ISDIR(status.st_mode) and _utf8(name):
            try:
                child = _open_folder(name, folder)
            except FileNotFoundError, NotADirectoryError:
                continue
            try:
                _walk(child, f"{path}/", depth=depth + 1, entries=entries, budget=budget)
            finally:
                os.close(child)
        elif stat.S_ISREG(status.st_mode) and _utf8(name):
            too_large = status.st_size > MAX_SKILL_FILE_BYTES
            entries.append(_Entry(path, _TOO_LARGE if too_large else None))
        else:
            entries.append(_Entry(path, _UNREADABLE))


def _refuse_early(entries: list[_Entry]) -> None:
    """Refuse the unit from the walk alone, before any byte is read, as ``_read_in_order``
    would: at the first problem in path order, or once more files than a unit holds come
    before it. A refused unit so costs only stats."""
    for files, entry in enumerate(entries):
        if entry.problem is not None:
            raise _RefusedError(entry.problem)
        if files >= MAX_UNIT_FILES:
            raise _RefusedError(_TOO_LARGE)


def _read_in_order(root: int, entries: list[_Entry]) -> list[UnitFile]:
    """Each entry's file under the unit's folder ``root``, in path order, stopping at the first
    problem; each folder on the way is opened again without following a link, and a file or
    folder that vanished since the walk is skipped."""
    found: list[UnitFile] = []
    for entry in entries:
        if entry.problem is not None:
            raise _RefusedError(entry.problem)
        if len(found) >= MAX_UNIT_FILES:
            raise _RefusedError(_TOO_LARGE)
        try:
            found.append(_read_below(root, entry.path))
        except FileNotFoundError, NotADirectoryError:
            continue
    return found


def _read_below(root: int, path: str) -> UnitFile:
    *folders, name = path.split("/")
    opened: list[int] = []
    try:
        parent = root
        for folder in folders:
            parent = _open_folder(folder, parent)
            opened.append(parent)
        return _read_file(parent, name, path)
    finally:
        for descriptor in opened:
            os.close(descriptor)


def _names(folder: int, budget: _Budget) -> list[str]:
    """The names in ``folder``, hidden ones left out, in name order; each one counted."""
    names: list[str] = []
    with os.scandir(folder) as found:
        for entry in found:
            budget.names -= 1
            if budget.names < 0:
                raise _RefusedError(_TOO_LARGE)
            if not entry.name.startswith("."):
                names.append(entry.name)
    return sorted(names)


def _utf8(name: str) -> bool:
    try:
        name.encode()
    except UnicodeEncodeError:
        return False
    return True


def _read_file(folder: int, name: str, path: str) -> UnitFile:
    """The regular file ``name`` under ``folder`` as the unit's file ``path``; a special file is
    refused before it is opened, and again from ``fstat`` should it be swapped in between."""
    if not stat.S_ISREG(os.stat(name, dir_fd=folder, follow_symlinks=False).st_mode):
        raise _RefusedError(_UNREADABLE)
    descriptor = os.open(name, _FILE_FLAGS, dir_fd=folder)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise _RefusedError(_UNREADABLE)
        if status.st_size > MAX_SKILL_FILE_BYTES:
            raise _RefusedError(_TOO_LARGE)
        content = _read_at_most(descriptor, MAX_SKILL_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(content) > MAX_SKILL_FILE_BYTES:
        raise _RefusedError(_TOO_LARGE)
    executable = bool(status.st_mode & stat.S_IXUSR)
    return UnitFile(path=path, content=content, executable=executable)


def _open_folder(name: str, parent: int) -> int:
    """``name`` opened as a folder under ``parent``; a link raises ``ELOOP`` on every system
    (Linux says ``ENOTDIR`` for a linked folder opened with ``O_DIRECTORY | O_NOFOLLOW``)."""
    try:
        return os.open(name, _FOLDER_FLAGS, dir_fd=parent)
    except NotADirectoryError:
        if stat.S_ISLNK(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
            raise OSError(errno.ELOOP, "a link") from None
        raise


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


def _unread(error: OSError) -> UnreadUnit:
    # A folder on the way that is a file reads as absent; a link met (ELOOP) or any other
    # failure is unreadable.
    if error.errno in {errno.ENOENT, errno.ENOTDIR}:
        return _MISSING
    return _UNREADABLE
