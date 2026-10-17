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
here, the listing's own budget is never trusted. Hidden names inside a skill folder are left
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
    """What a folder walk may still take: files (``SKILL.md`` and the bundled ones) and names."""

    files: int = MAX_UNIT_FILES
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
    folder = _open_folder(name, parent)
    found: list[UnitFile] = []
    try:
        _walk(folder, "", depth=1, found=found, budget=_Budget())
    finally:
        os.close(folder)
    found.sort(key=lambda file: file.path)
    if not any(file.path == SKILL_FILE for file in found):
        return _MISSING
    return UnitContent(files=tuple(found))


def _walk(folder: int, above: str, *, depth: int, found: list[UnitFile], budget: _Budget) -> None:
    """The files of ``folder`` into ``found``, each path after ``above`` (the folder's own path
    in the unit and a ``/``); its entries are ``depth`` segments below the skill's folder."""
    for name in _names(folder, budget):
        if depth > DEFAULT_LIMITS.skill_depth:
            raise _RefusedError(_TOO_LARGE)
        status = os.stat(name, dir_fd=folder, follow_symlinks=False)
        path = f"{above}{name}"
        if stat.S_ISDIR(status.st_mode):
            child = _open_folder(name, folder)
            try:
                _walk(child, f"{path}/", depth=depth + 1, found=found, budget=budget)
            finally:
                os.close(child)
        elif stat.S_ISREG(status.st_mode):
            if budget.files <= 0:
                raise _RefusedError(_TOO_LARGE)
            budget.files -= 1
            found.append(_read_file(folder, name, path))
        else:
            raise _RefusedError(_UNREADABLE)


def _names(folder: int, budget: _Budget) -> list[str]:
    """The names in ``folder``, hidden ones left out, in name order; each one counted."""
    names: list[str] = []
    with os.scandir(folder) as entries:
        for entry in entries:
            budget.names -= 1
            if budget.names < 0:
                raise _RefusedError(_TOO_LARGE)
            if entry.name.startswith("."):
                continue
            try:
                entry.name.encode()
            except UnicodeEncodeError:
                raise _RefusedError(_UNREADABLE) from None
            names.append(entry.name)
    return sorted(names)


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
