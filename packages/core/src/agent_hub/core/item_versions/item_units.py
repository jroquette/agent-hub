"""The versioned unit of a Toolkit item (AGH-295, S1, D5, D7, A4).

A skill's unit is its folder (the parent of its ``SKILL.md``), an agent's its file, a hook's the
whole file that holds it, so every hook of one file shares one unit. An item whose own listing
entry is a link has no unit: a link inside the hub is versioned once, at its target (which
carries ``linked_from``), and a link out of it not at all. ``settings.local.json`` is never a
unit. A unit is managed when ``hub.lock`` holds a managed entry for its main path: a skill's
``SKILL.md``, otherwise the file itself. ``unit_parts`` is the path rule a unit is read by: a
skill folder, an agent file, a hook file or a hub workflow file, each where its kind lives.
"""

import bisect
import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.doctor.snapshot import LockState
from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry, ManagedLinkEntry
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.skills.skill_sources import (
    AGENTS_FOLDER,
    CLAUDE_FOLDER,
    HOOKS_FILE,
    HOOKS_FOLDER,
    LOCAL_SETTINGS_PATH,
    PROJECT_SETTINGS_PATH,
    SETTINGS_PATH,
    SKILL_FILE,
    SKILLS_FOLDER,
    SkillPathError,
    SkillSources,
    SourceFile,
    skill_relative,
)
from agent_hub.core.skills.skill_view import CatalogItem, ItemKind
from agent_hub.core.workflows.catalog import HUB_WORKFLOWS_FOLDER

_UNIT_KINDS: Final = {
    ItemKind.SKILL: UnitKind.SKILL,
    ItemKind.AGENT: UnitKind.AGENT,
    ItemKind.HOOK: UnitKind.HOOK,
}
_SKILL_SUFFIX: Final = f"/{SKILL_FILE}"

# A unit's folder (skill, agent) is ``.claude/<folder>`` or ``plugin/<p>/<folder>``, by length.
_UNIT_DEPTHS: Final = {CLAUDE_FOLDER: 3, "plugin": 4}
_HOOK_SETTINGS: Final = frozenset({SETTINGS_PATH, PROJECT_SETTINGS_PATH})
_WORKFLOW_SEGMENTS: Final = 3
# A scenario file, ``scenarios/<pack>/<name>.yaml``, is shaped as a hub workflow's.
HUB_SCENARIOS_FOLDER: Final = "scenarios"
# An action's document or script, ``actions/<pack>/…``.
HUB_ACTIONS_UNIT_FOLDER: Final = "actions"
_WORKFLOW_SUFFIXES: Final = (".yaml", ".json")
_REFUSED: Final = "Path is not a unit of its kind"
_BAD_CHARACTER: Final = re.compile(r"[\\\x00-\x1f\x7f]")

# One listing entry as the capture memo compares it: path, size, mtime_ns, regular, link target.
type FingerprintEntry = tuple[str, int, int, bool, str | None]


class ItemUnit(BaseModel):
    """A versioned unit: ``unit_path`` is hub-relative, without a trailing slash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str = Field(min_length=1)
    unit_path: str = Field(min_length=1)
    kind: UnitKind


class SourceIndex:
    """One listing, indexed once for every unit of a read: by path, and in path order for the
    range below a folder. ``SkillSources.files`` is already in path order (the port's contract),
    so nothing is sorted again and no entry is visited twice to index it."""

    def __init__(self, sources: SkillSources) -> None:
        self._files = sources.files
        paths: list[str] = []
        self._by_path: dict[str, SourceFile] = {}
        for entry in self._files:
            paths.append(entry.path)
            self._by_path.setdefault(entry.path, entry)
        # Aligned with ``_files`` index for index, so a range of paths is a slice of entries.
        self._paths = tuple(paths)

    def entry(self, path: str) -> SourceFile | None:
        """The entry at ``path``, or None when the listing does not hold it."""
        return self._by_path.get(path)

    def at_or_under(self, path: str) -> tuple[SourceFile, ...]:
        """The entry at ``path`` and every entry below it as a folder, in path order."""
        # Every path starting ``<path>/`` sorts at or after it and before ``<path>0``
        # (``0`` is the character after ``/``).
        low = bisect.bisect_left(self._paths, f"{path}/")
        high = bisect.bisect_left(self._paths, f"{path}0", lo=low)
        exact = self._by_path.get(path)
        below = self._files[low:high] if high > low else ()
        return below if exact is None else (exact, *below)


def unit_of_item(item: CatalogItem, index: SourceIndex, *, project: str) -> ItemUnit | None:
    """The unit ``item`` of ``project`` is versioned in, or None (a link, local settings, an
    entry the listing does not hold)."""
    path = item.source_path
    if path == LOCAL_SETTINGS_PATH:
        return None
    entry = index.entry(path)
    if entry is None or entry.link_target is not None:
        return None
    kind = _UNIT_KINDS[item.kind]
    if kind is UnitKind.SKILL:
        path = path.removesuffix(_SKILL_SUFFIX)
    return ItemUnit(project=project, unit_path=path, kind=kind)


def unit_fingerprint(index: SourceIndex, unit: ItemUnit) -> tuple[FingerprintEntry, ...]:
    """The listing's entries at or under ``unit``, in path order: what changes when its content
    may have changed (D17: an edit keeping size and mtime is noticed at the next real change)."""
    return tuple(
        (entry.path, entry.size, entry.mtime_ns, entry.regular, entry.link_target)
        for entry in index.at_or_under(unit.unit_path)
    )


def is_managed(lock: LockState | None, unit: ItemUnit) -> bool:
    """True when ``hub.lock`` holds a managed entry for ``unit``'s main path (A4)."""
    if not isinstance(lock, HubLock):
        return False
    main = f"{unit.unit_path}{_SKILL_SUFFIX}" if unit.kind is UnitKind.SKILL else unit.unit_path
    return isinstance(lock.files.get(main), ManagedFileEntry | ManagedLinkEntry)


def unit_parts(unit_path: str, kind: UnitKind) -> tuple[str, ...]:
    """``unit_path``'s segments when it is a unit of ``kind``, or ``SkillPathError``: a skill
    folder ``.claude/skills/<n>`` or ``plugin/<p>/skills/<n>``, an agent file ``.claude/agents/
    <n>.md`` or ``plugin/<p>/agents/<n>.md``, a hook file (``.claude/settings.json``,
    ``.claude/settings.project.json``, ``plugin/<p>/hooks/hooks.json``), a workflow file
    ``workflows/<pack>/<n>.yaml`` or ``.json``, a scenario file ``scenarios/<pack>/<n>.yaml``.
    Never ``settings.local.json``; never touches the disk."""
    if kind is UnitKind.WORKFLOW:
        return _workflow_parts(unit_path)
    if kind is UnitKind.SCENARIO:
        return _workflow_parts(unit_path, folder=HUB_SCENARIOS_FOLDER)
    if kind is UnitKind.ACTION:
        return _action_parts(unit_path)
    checked = f"{unit_path}/{SKILL_FILE}" if kind is UnitKind.SKILL else unit_path
    segments = skill_relative(checked).parts
    if kind is UnitKind.SKILL:
        segments = segments[:-1]
    if kind is UnitKind.HOOK:
        accepted = unit_path in _HOOK_SETTINGS or segments[2:] == (HOOKS_FOLDER, HOOKS_FILE)
    else:
        folder = SKILLS_FOLDER if kind is UnitKind.SKILL else AGENTS_FOLDER
        depth = _UNIT_DEPTHS.get(segments[0])
        accepted = len(segments) == depth and segments[-2] == folder
    if not accepted:
        raise SkillPathError(_REFUSED)
    return segments


def _action_parts(unit_path: str) -> tuple[str, ...]:
    """An action's document ``actions/<pack>/<n>.yaml`` or its script
    ``actions/<pack>/scripts/<file>`` (``.py`` or ``.sh``)."""
    segments = tuple(unit_path.split("/"))
    plain = all(segment and not segment.startswith(".") for segment in segments) and not (
        _BAD_CHARACTER.search(unit_path)
    )
    document = len(segments) == _WORKFLOW_SEGMENTS and segments[-1].endswith(".yaml")
    script = (
        len(segments) == _WORKFLOW_SEGMENTS + 1
        and segments[2] == "scripts"
        and segments[-1].endswith((".py", ".sh"))
    )
    if not (plain and segments[0] == HUB_ACTIONS_UNIT_FOLDER and (document or script)):
        raise SkillPathError(_REFUSED)
    return segments


def _workflow_parts(unit_path: str, *, folder: str = HUB_WORKFLOWS_FOLDER) -> tuple[str, ...]:
    segments = tuple(unit_path.split("/"))
    shaped = (
        len(segments) == _WORKFLOW_SEGMENTS
        and segments[0] == folder
        and segments[-1].endswith(_WORKFLOW_SUFFIXES)
        and all(segment and not segment.startswith(".") for segment in segments)
        and not _BAD_CHARACTER.search(unit_path)
    )
    if not shaped:
        raise SkillPathError(_REFUSED)
    return segments
