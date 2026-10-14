"""The skill source port's types and its pure path rule (AGH-164, S1, P1, L5).

``HubFileReader.skill_sources`` lists, stat-only, every entry under the skill roots of a hub;
``read_skill_file`` reads one path ``skill_relative`` accepts, never through a link. The roots:
``.claude/skills/<n>/**``, ``.claude/agents/*.md``, ``.claude/settings.json``,
``.claude/settings.project.json``, ``.claude-plugin/marketplace.json``, ``hub.lock``,
``plugin/<p>/skills/<n>/**`` (at most ``skill_depth`` segments below ``<n>``),
``plugin/<p>/agents/*.md`` and ``plugin/<p>/hooks/hooks.json``. Never
``.claude/settings.local.json`` (personal). The rule never touches the disk: the adapter still
refuses links and non-regular files on its own. Clients address items and bundled files by id;
ids map to paths only here in core, from a fresh listing.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

from agent_hub.core.brain.brain_path import MAX_NOTE_BYTES, MAX_PATH_CHARS
from agent_hub.core.doctor.snapshot import LockState
from agent_hub.core.errors import AgentHubError
from agent_hub.core.skills.skill_view import FileRole, SkillCatalog, SkillDetail

if TYPE_CHECKING:
    from agent_hub.core.hubs.hub_registry import UnreadHubFile

# Every bound the 16 MiB budget and the file caps share (S9, L5).
CATALOG_BUDGET_BYTES: Final = 16 * 1_048_576
MAX_HOOKS: Final = 2_000
MAX_SKILL_JSON_BYTES: Final = 1_048_576
# ``SKILL.md``, an agent file or a bundled file is read up to this size (as brain notes).
MAX_SKILL_FILE_BYTES: Final = MAX_NOTE_BYTES

SKILL_FILE: Final = "SKILL.md"
AGENT_SUFFIX: Final = ".md"
CLAUDE_FOLDER: Final = ".claude"
PLUGIN_FOLDER: Final = "plugin"
SKILLS_FOLDER: Final = "skills"
AGENTS_FOLDER: Final = "agents"
HOOKS_FOLDER: Final = "hooks"
HOOKS_FILE: Final = "hooks.json"
SETTINGS_PATH: Final = ".claude/settings.json"
PROJECT_SETTINGS_PATH: Final = ".claude/settings.project.json"
LOCAL_SETTINGS_PATH: Final = ".claude/settings.local.json"
MARKETPLACE_PATH: Final = ".claude-plugin/marketplace.json"
LOCK_PATH: Final = "hub.lock"
# The single files under the roots, by hub-relative path.
SINGLE_FILES: Final = frozenset({SETTINGS_PATH, PROJECT_SETTINGS_PATH, MARKETPLACE_PATH, LOCK_PATH})

# Sources that are not plugin folders (L5): a plugin folder with one of these names is skipped.
CLAUDE_SOURCE: Final = "claude"
SETTINGS_SOURCE: Final = "settings"
PROJECT_SETTINGS_SOURCE: Final = "settings-project"
RESERVED_SOURCES: Final = frozenset({CLAUDE_SOURCE, SETTINGS_SOURCE, PROJECT_SETTINGS_SOURCE})
# The managed base plugin's folder.
BASE_PLUGIN: Final = "hub-workflow"

_FILE_ID_HEX: Final = 16
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_ROLE_LABELS: Final[Mapping[FileRole, str]] = {
    "scripts": "executed at invocation",
    "references": "read on demand",
    "assets": "assets",
    "other": "other",
}
_ROLES: Final[Mapping[str, FileRole]] = {
    "scripts": "scripts",
    "references": "references",
    "assets": "assets",
}
# ``plugin/<p>/<folder>/...``: at least the folder and one name below it.
_PLUGIN_ITEM_SEGMENTS: Final = 4
# ``.claude/<folder>/<name>``: the folder and one name.
_CLAUDE_ITEM_SEGMENTS: Final = 3


@dataclass(frozen=True, kw_only=True, slots=True)
class SkillLimits:
    """The listing's bounds (L5, inputs table): entries per kind (skill folders, agent files),
    files per skill, depth below a skill folder, names examined, plugin folders, and the
    characters of a link's target text (a longer target counts as outside the hub)."""

    items_per_kind: int = 500
    files_per_skill: int = 200
    skill_depth: int = 3
    names_examined: int = 20_000
    plugin_folders: int = 50
    link_chars: int = 512


DEFAULT_LIMITS: Final = SkillLimits()


@dataclass(frozen=True, kw_only=True, slots=True)
class SourceFile:
    """One entry under the roots, as ``lstat`` saw it; nothing is opened to list it.

    ``regular`` is true for a regular file. A link has ``regular`` false and ``link_target`` its
    text as ``readlink`` gave it, ``""`` when the text could not be read or is longer than
    ``SkillLimits.link_chars`` (core then treats it as outside the hub); a link is never
    followed, so nothing under a linked folder is listed. Any other entry (a FIFO, a socket)
    has ``regular`` false and no ``link_target``. Folders are walked, never listed.
    """

    path: str
    size: int
    mtime_ns: int
    regular: bool
    link_target: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class SkillSources:
    """The entries under a hub's skill roots in path order; ``truncated`` when a bound stopped
    the walk, ``skipped`` the entries left out (unreadable folders, past a bound, non-UTF-8
    names). A missing root lists nothing."""

    files: tuple[SourceFile, ...]
    truncated: bool = False
    skipped: int = 0


@dataclass(frozen=True, kw_only=True, slots=True)
class CatalogInputs:
    """What the catalog fold reads (C1), all gathered by the reads use case (C2).

    ``project_plugin`` is the project's own plugin folder (``project.name``); ``texts`` holds,
    by hub-relative path, what ``read_skill_file`` returned for each file read (``SKILL.md``,
    agent files, the settings files, ``hooks.json``, the marketplace); ``lock`` is ``hub.lock``
    as ``read_lock`` found it; ``over_budget`` the paths left unread once the catalog's byte
    budget ran out.
    """

    project: str
    project_plugin: str
    sources: SkillSources
    texts: Mapping[str, bytes | UnreadHubFile]
    lock: LockState | None
    over_budget: frozenset[str] = frozenset()


@dataclass(frozen=True, kw_only=True, slots=True)
class FoldedCatalog:
    """The fold's result: the catalog without usage, each item's detail by item id, and each
    item's bundled files as file id -> hub-relative path (the only place ids become paths)."""

    catalog: SkillCatalog
    details: Mapping[str, SkillDetail] = field(default_factory=dict)
    files: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


class SkillPathError(AgentHubError):
    """A path the skill rules refuse; ``reason`` says why, never quoting the path."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_OUTSIDE: Final = "Path is outside the skill roots"


def _refuse_characters(path: str) -> None:
    if not path:
        raise SkillPathError("Path is empty")
    if len(path) > MAX_PATH_CHARS:
        raise SkillPathError(f"Path is longer than {MAX_PATH_CHARS} characters")
    if "\\" in path or _CONTROL.search(path):
        raise SkillPathError("Path holds a backslash or a control character")
    if path.startswith("/"):
        raise SkillPathError("Path must be relative to the hub")


def _refuse_hidden(segments: list[str]) -> None:
    if any(not segment or segment.startswith(".") for segment in segments):
        raise SkillPathError("Path has an empty, hidden or parent segment")


def _skill_folder_path(below: list[str], *, depth: int) -> bool:
    # ``<n>`` itself (a folder or a link) or a file at most ``depth`` segments below it.
    _refuse_hidden(below)
    return 1 <= len(below) <= depth + 1


def _agent_file(name: list[str]) -> bool:
    _refuse_hidden(name)
    return len(name) == 1 and name[0].endswith(AGENT_SUFFIX) and name[0] != AGENT_SUFFIX


def _claude_path(segments: list[str], *, depth: int) -> bool:
    if len(segments) < _CLAUDE_ITEM_SEGMENTS:
        return False
    folder, rest = segments[1], segments[2:]
    if folder == SKILLS_FOLDER:
        return _skill_folder_path(rest, depth=depth)
    return folder == AGENTS_FOLDER and _agent_file(rest)


def _plugin_path(segments: list[str], *, depth: int) -> bool:
    if len(segments) < _PLUGIN_ITEM_SEGMENTS:
        return False
    _refuse_hidden(segments[1:2])
    folder, rest = segments[2], segments[3:]
    if folder == SKILLS_FOLDER:
        return _skill_folder_path(rest, depth=depth)
    if folder == AGENTS_FOLDER:
        return _agent_file(rest)
    return folder == HOOKS_FOLDER and rest == [HOOKS_FILE]


def skill_relative(path: str, *, depth: int = DEFAULT_LIMITS.skill_depth) -> PurePosixPath:
    """``path`` as a hub-relative path under the skill roots, or ``SkillPathError``.

    Refused: an empty, absolute or over-long path, a backslash or control character, an empty,
    hidden, ``.`` or ``..`` segment below a root, ``.claude/settings.local.json``, and any path
    outside the roots (a skill file more than ``depth`` segments below its folder included).
    """
    _refuse_characters(path)
    if path == LOCAL_SETTINGS_PATH:
        raise SkillPathError("Personal settings are never read")
    if path in SINGLE_FILES:
        return PurePosixPath(path)
    segments = path.split("/")
    if segments[0] == CLAUDE_FOLDER:
        accepted = _claude_path(segments, depth=depth)
    elif segments[0] == PLUGIN_FOLDER:
        accepted = _plugin_path(segments, depth=depth)
    else:
        accepted = False
    if not accepted:
        raise SkillPathError(_OUTSIDE)
    return PurePosixPath(*segments)


def role_of(skill_relative_path: str) -> FileRole:
    """A bundled file's role from the first folder of its path in the skill folder (S7): a file
    directly in the skill folder is ``other``."""
    first, slash, _ = skill_relative_path.partition("/")
    return _ROLES.get(first, "other") if slash else "other"


def role_label(role: FileRole) -> str:
    """What a role means to the owner: ``scripts`` "executed at invocation", ``references``
    "read on demand"."""
    return _ROLE_LABELS[role]


def file_id(path: str) -> str:
    """The server-issued id of a bundled file: 16 hex digits of the sha256 of its hub-relative
    path (S7)."""
    return hashlib.sha256(path.encode()).hexdigest()[:_FILE_ID_HEX]
