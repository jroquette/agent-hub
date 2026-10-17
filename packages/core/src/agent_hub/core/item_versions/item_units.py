"""The versioned unit of a Toolkit item (AGH-295, S1, D5, D7, A4).

A skill's unit is its folder (the parent of its ``SKILL.md``), an agent's its file, a hook's the
whole file that holds it, so every hook of one file shares one unit. An item whose own listing
entry is a link has no unit: a link inside the hub is versioned once, at its target (which
carries ``linked_from``), and a link out of it not at all. ``settings.local.json`` is never a
unit. A unit is managed when ``hub.lock`` holds a managed entry for its main path: a skill's
``SKILL.md``, otherwise the file itself.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.doctor.snapshot import LockState
from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry, ManagedLinkEntry
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.skills.skill_sources import LOCAL_SETTINGS_PATH, SKILL_FILE, SkillSources
from agent_hub.core.skills.skill_view import CatalogItem, ItemKind

_UNIT_KINDS: Final = {
    ItemKind.SKILL: UnitKind.SKILL,
    ItemKind.AGENT: UnitKind.AGENT,
    ItemKind.HOOK: UnitKind.HOOK,
}
_SKILL_SUFFIX: Final = f"/{SKILL_FILE}"

# One listing entry as the capture memo compares it: path, size, mtime_ns, regular, link target.
type FingerprintEntry = tuple[str, int, int, bool, str | None]


class ItemUnit(BaseModel):
    """A versioned unit: ``unit_path`` is hub-relative, without a trailing slash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str = Field(min_length=1)
    unit_path: str = Field(min_length=1)
    kind: UnitKind


def unit_of_item(item: CatalogItem, sources: SkillSources, *, project: str) -> ItemUnit | None:
    """The unit ``item`` of ``project`` is versioned in, or None (a link, local settings, an
    entry the listing does not hold)."""
    path = item.source_path
    if path == LOCAL_SETTINGS_PATH:
        return None
    entry = next((found for found in sources.files if found.path == path), None)
    if entry is None or entry.link_target is not None:
        return None
    kind = _UNIT_KINDS[item.kind]
    if kind is UnitKind.SKILL:
        path = path.removesuffix(_SKILL_SUFFIX)
    return ItemUnit(project=project, unit_path=path, kind=kind)


def unit_fingerprint(sources: SkillSources, unit: ItemUnit) -> tuple[FingerprintEntry, ...]:
    """The listing's entries at or under ``unit``, in path order: what changes when its content
    may have changed (D17: an edit keeping size and mtime is noticed at the next real change)."""
    below = f"{unit.unit_path}/"
    return tuple(
        (entry.path, entry.size, entry.mtime_ns, entry.regular, entry.link_target)
        for entry in sorted(sources.files, key=lambda found: found.path)
        if entry.path == unit.unit_path or entry.path.startswith(below)
    )


def is_managed(lock: LockState | None, unit: ItemUnit) -> bool:
    """True when ``hub.lock`` holds a managed entry for ``unit``'s main path (A4)."""
    if not isinstance(lock, HubLock):
        return False
    main = f"{unit.unit_path}{_SKILL_SUFFIX}" if unit.kind is UnitKind.SKILL else unit.unit_path
    return isinstance(lock.files.get(main), ManagedFileEntry | ManagedLinkEntry)
