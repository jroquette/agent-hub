"""Read a hub's skills, agents and hooks for the Skills tab (AGH-164, S1, P1).

``list_skill_sources`` lists every entry under core's skill roots, stat-only and bounded;
``read_skill_file`` reads one path core's ``skill_relative`` accepts, never through a link, a
regular file of at most ``max_bytes``. Both follow ``brain_files``' read policy (its helpers are
copied here, adapters never import each other): each folder is opened relative to its parent
(``os.open(name, O_DIRECTORY | O_NOFOLLOW, dir_fd=parent)``), so a linked folder is never
entered; an entry is looked at with ``os.stat(name, dir_fd=, follow_symlinks=False)``; a link's
target is read as text only (``os.readlink(name, dir_fd=)``), never opened; a file is opened with
``O_NOFOLLOW | O_NONBLOCK`` (a FIFO never blocks) and read only when ``fstat`` says it is
regular. Messages are one line and never hold a path.

The walk visits, in name order: ``.claude/{settings.json,settings.project.json}``,
``.claude/skills/<n>/**``, ``.claude/agents/*.md``, ``.claude-plugin/marketplace.json``,
``hub.lock``, and per plugin folder ``plugin/<p>/skills/<n>/**``, ``plugin/<p>/agents/*.md`` and
``plugin/<p>/hooks/hooks.json``; never ``.claude/settings.local.json``, hidden names or a file
more than ``skill_depth`` segments below its skill folder. Bounds (``SkillLimits``): names read
from folders, plugin folders, entries per kind (skill folders, agent files) and files per skill
folder (``SKILL.md`` plus ``files_per_skill``); a bound left reached sets ``truncated`` and
counts what it left out in ``skipped``, as do unreadable folders and names that are not UTF-8.
The result is in path order.
"""

import contextlib
import errno
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.skills.skill_sources import (
    AGENT_SUFFIX,
    AGENTS_FOLDER,
    CLAUDE_FOLDER,
    HOOKS_FILE,
    HOOKS_FOLDER,
    LOCK_PATH,
    MARKETPLACE_PATH,
    PLUGIN_FOLDER,
    PROJECT_SETTINGS_PATH,
    SETTINGS_PATH,
    SKILLS_FOLDER,
    SkillLimits,
    SkillPathError,
    SkillSources,
    SourceFile,
    skill_relative,
)

_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_CHUNK: Final = 65_536
# The single files directly under the hub's folders, by folder.
_CLAUDE_FILES: Final = tuple(
    path.rpartition("/")[2] for path in sorted({SETTINGS_PATH, PROJECT_SETTINGS_PATH})
)
_MARKETPLACE_FOLDER, _, _MARKETPLACE_FILE = MARKETPLACE_PATH.partition("/")
# One line each; never a path, so a message cannot reveal where a link points.
_MISSING: Final = UnreadHubFile(
    message="cannot read: no such file", is_missing=True, kind="missing"
)
_NOT_REGULAR: Final = UnreadHubFile(
    message="cannot read: not a regular file", is_missing=False, kind="not_regular"
)


class _SpentError(Exception):
    """The walk read as many names as ``names_examined`` allows."""


@dataclass(frozen=True, slots=True)
class _At:
    """An open folder of the walk and its hub-relative path (``""`` for the hub itself)."""

    fd: int
    path: str

    def child(self, name: str) -> str:
        return f"{self.path}/{name}" if self.path else name


@dataclass(kw_only=True, slots=True)
class _Walk:
    limits: SkillLimits
    files: list[SourceFile] = field(default_factory=list)
    items: dict[str, int] = field(default_factory=dict)
    examined: int = 0
    skipped: int = 0
    truncated: bool = False

    def cap(self) -> None:
        self.truncated = True
        self.skipped += 1

    def take_item(self, kind: str) -> bool:
        """Whether one more entry of ``kind`` fits; a refusal is counted as a cap."""
        if self.items.get(kind, 0) >= self.limits.items_per_kind:
            self.cap()
            return False
        self.items[kind] = self.items.get(kind, 0) + 1
        return True

    def add(self, at: _At, name: str, status: os.stat_result) -> None:
        self.files.append(_source_file(at, name, status, limits=self.limits))


def list_skill_sources(hub_root: Path, limits: SkillLimits) -> SkillSources:
    """Every entry under the skill roots of ``hub_root`` in path order, within ``limits``;
    nothing when the hub or a root is absent."""
    walk = _Walk(limits=limits)
    try:
        hub = os.open(hub_root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return SkillSources(files=())
    try:
        _walk_hub(_At(hub, ""), walk)
    except _SpentError:
        walk.truncated = True
    finally:
        os.close(hub)
    files = sorted(walk.files, key=lambda entry: entry.path)
    return SkillSources(files=tuple(files), truncated=walk.truncated, skipped=walk.skipped)


def read_skill_file(hub_root: Path, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
    """The bytes of the hub-relative ``path`` when it is a regular file of at most ``max_bytes``,
    or why not (``missing``, ``not_regular``, ``too_large`` or ``unreadable``); a path
    ``skill_relative`` refuses reads ``missing`` without touching the disk."""
    try:
        parts = skill_relative(path).parts
    except SkillPathError:
        return _MISSING
    try:
        with _opened_folders(hub_root, parts[:-1]) as folder:
            descriptor = os.open(parts[-1], _FILE_FLAGS, dir_fd=folder)
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


# The walk


def _walk_hub(hub: _At, walk: _Walk) -> None:
    with _folder(hub, CLAUDE_FOLDER, walk) as claude:
        if claude is not None:
            _single_files(claude, _CLAUDE_FILES, walk)
            _agents(claude, walk)
            _skills(claude, walk)
    with _folder(hub, _MARKETPLACE_FOLDER, walk) as marketplace:
        if marketplace is not None:
            _single_files(marketplace, (_MARKETPLACE_FILE,), walk)
    _single_files(hub, (LOCK_PATH,), walk)
    with _folder(hub, PLUGIN_FOLDER, walk) as plugins:
        if plugins is not None:
            _plugins(plugins, walk)


def _plugins(plugins: _At, walk: _Walk) -> None:
    seen = 0
    for name, status in _entries(plugins, walk):
        if not stat.S_ISDIR(status.st_mode):
            continue
        if seen >= walk.limits.plugin_folders:
            walk.cap()
            continue
        seen += 1
        with _folder(plugins, name, walk) as plugin:
            if plugin is None:
                continue
            _agents(plugin, walk)
            _skills(plugin, walk)
            with _folder(plugin, HOOKS_FOLDER, walk) as hooks:
                if hooks is not None:
                    _single_files(hooks, (HOOKS_FILE,), walk)


def _agents(parent: _At, walk: _Walk) -> None:
    """The ``agents/*.md`` entries under ``parent`` (files, links, special files)."""
    with _folder(parent, AGENTS_FOLDER, walk) as agents:
        if agents is None:
            return
        for name, status in _entries(agents, walk):
            if stat.S_ISDIR(status.st_mode) or not _agent_name(name):
                continue
            if walk.take_item(AGENTS_FOLDER):
                walk.add(agents, name, status)


def _skills(parent: _At, walk: _Walk) -> None:
    """The ``skills/<n>`` entries under ``parent``: a folder is walked, anything else listed."""
    with _folder(parent, SKILLS_FOLDER, walk) as skills:
        if skills is None:
            return
        for name, status in _entries(skills, walk):
            if not walk.take_item(SKILLS_FOLDER):
                continue
            if not stat.S_ISDIR(status.st_mode):
                walk.add(skills, name, status)
                continue
            with _folder(skills, name, walk) as skill:
                if skill is not None:
                    _skill_files(skill, walk, depth=1, budget=[walk.limits.files_per_skill + 1])


def _skill_files(at: _At, walk: _Walk, *, depth: int, budget: list[int]) -> None:
    """The files of the skill folder ``at``, ``depth`` segments down from the skill's own
    folder (1 for it), sharing ``budget`` (``SKILL.md`` and the bundled files left)."""
    subfolders: list[str] = []
    for name, status in _entries(at, walk):
        if stat.S_ISDIR(status.st_mode):
            if depth < walk.limits.skill_depth:
                subfolders.append(name)
            continue
        if budget[0] <= 0:
            walk.cap()
            continue
        budget[0] -= 1
        walk.add(at, name, status)
    for name in subfolders:
        with _folder(at, name, walk) as folder:
            if folder is not None:
                _skill_files(folder, walk, depth=depth + 1, budget=budget)


def _single_files(at: _At, names: tuple[str, ...], walk: _Walk) -> None:
    for name in names:
        try:
            status = os.stat(name, dir_fd=at.fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError:
            walk.skipped += 1
            continue
        if not stat.S_ISDIR(status.st_mode):
            walk.add(at, name, status)


def _agent_name(name: str) -> bool:
    return name.endswith(AGENT_SUFFIX) and name != AGENT_SUFFIX


@contextlib.contextmanager
def _folder(parent: _At, name: str, walk: _Walk) -> Iterator[_At | None]:
    """``name`` under ``parent`` opened as a folder without following a link; None when it is
    absent, a link or not a folder, and counted in ``skipped`` when it cannot be read."""
    try:
        descriptor = os.open(name, _FOLDER_FLAGS, dir_fd=parent.fd)
    except FileNotFoundError, NotADirectoryError:
        descriptor = None
    except OSError as error:
        if error.errno != errno.ELOOP:
            walk.skipped += 1
        descriptor = None
    try:
        yield None if descriptor is None else _At(descriptor, parent.child(name))
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _entries(at: _At, walk: _Walk) -> list[tuple[str, os.stat_result]]:
    """The names in ``at`` with their ``lstat``, in name order: hidden names dropped, a name
    that is not UTF-8 or cannot be looked at counted in ``skipped``. Raises ``_SpentError``
    once the walk has read ``names_examined`` names."""
    names: list[str] = []
    try:
        with os.scandir(at.fd) as found:
            for entry in found:
                if walk.examined >= walk.limits.names_examined:
                    raise _SpentError
                walk.examined += 1
                name = entry.name
                if name.startswith("."):
                    continue
                try:
                    name.encode()
                except UnicodeEncodeError:
                    walk.skipped += 1
                    continue
                names.append(name)
    except OSError:
        walk.skipped += 1
    listed: list[tuple[str, os.stat_result]] = []
    for name in sorted(names):
        try:
            listed.append((name, os.stat(name, dir_fd=at.fd, follow_symlinks=False)))
        except OSError:
            walk.skipped += 1
    return listed


def _source_file(at: _At, name: str, status: os.stat_result, *, limits: SkillLimits) -> SourceFile:
    link_target: str | None = None
    if stat.S_ISLNK(status.st_mode):
        link_target = _link_text(at, name, limits=limits)
    return SourceFile(
        path=at.child(name),
        size=status.st_size,
        mtime_ns=status.st_mtime_ns,
        regular=stat.S_ISREG(status.st_mode),
        link_target=link_target,
    )


def _link_text(at: _At, name: str, *, limits: SkillLimits) -> str:
    """The link's target as text, never resolved; ``""`` when unreadable, not UTF-8 or longer
    than ``link_chars`` (core then treats it as outside the hub)."""
    try:
        target = os.readlink(name, dir_fd=at.fd)
        target.encode()
    except OSError, UnicodeEncodeError:
        return ""
    return target if len(target) <= limits.link_chars else ""


# Reading one file (the ``brain_files`` helpers, copied)


@contextlib.contextmanager
def _opened_folders(hub_root: Path, folders: tuple[str, ...]) -> Iterator[int]:
    """The descriptor of ``<hub_root>/<folders>``, each level opened without following a link."""
    opened: list[int] = []
    try:
        parent = os.open(hub_root, os.O_RDONLY | os.O_DIRECTORY)
        opened.append(parent)
        for name in folders:
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
