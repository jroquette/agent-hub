"""Publish rules: what a Studio draft becomes in the hub (AGH-295, S5, D19, D24). Pure.

``read_draft_item`` reads a draft's files as an item of its kind, or refuses it with
``DraftInvalidError`` (422 ``draft_invalid``): a skill's ``SKILL.md`` or an agent's one top-level
``.md`` carries a frontmatter ``name`` within ``ITEM_NAME``; a hook's ``hooks.json`` is a hooks
object in the catalog's strict shape (at least one hook, at most ``MAX_HOOKS``), beside which only
``scripts/<file>`` may sit; no draft holds a hidden name (``scripts/.x``) or a script below a
folder of ``scripts/`` (``scripts/a/b.sh``).

``edit_destination`` places an edit of a skill (the item's files with the draft's over them, files
the draft lacks kept) or of an agent (the draft's file); a changed ``name`` moves it to the
sibling folder or file of that name and names the old unit for removal (D19). ``replace_hook``
replaces one hook of a hook file by the draft's hooks and keeps every other hook and key;
``merge_hooks`` adds hooks to a hook file (or a new one). Both write the file in ``dump_json``'s
form (D24). ``new_destination`` places a new item in the project's own plugin,
``plugin/<project>/``, a new hook's scripts in its ``scripts/``. No message names a path.
"""

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple

from agent_hub.core.errors import AgentHubError
from agent_hub.core.item_versions.hub_item_writer import ItemWriteRefusedError
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.json_form import InvalidJsonError, JsonValue, dump_json, load_json_bytes
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_frontmatter import read_skill_document
from agent_hub.core.skills.skill_hooks import hook_records
from agent_hub.core.skills.skill_sources import (
    AGENTS_FOLDER,
    HOOKS_FILE,
    HOOKS_FOLDER,
    PLUGIN_FOLDER,
    SKILL_FILE,
    SKILLS_FOLDER,
)
from agent_hub.core.skills.skill_view import ITEM_NAME, text_of

_ITEM_NAME: Final = re.compile(ITEM_NAME)
_AGENT_SUFFIX: Final = ".md"
_SCRIPTS_FOLDER: Final = "scripts"
_NAME_KEY: Final = "name"
_HOOKS_KEY: Final = "hooks"
_MATCHER_KEY: Final = "matcher"
# The keys a matcher group may hold to be spliced in place of the hook it replaces.
_SPLICED_KEYS: Final = frozenset({_HOOKS_KEY, _MATCHER_KEY})
# The plugin folder name the draft's hooks are folded under (only to check their shape).
_DRAFT_SOURCE: Final = "draft"
_NOT_HOOKS_FILE: Final = "The hooks file on disk is not a hooks object"

type HookGroups = Mapping[str, JsonValue]


class DraftInvalidError(AgentHubError):
    """A draft that is not a valid item of its kind (422 ``draft_invalid``); ``reason`` says why
    in words, naming no path."""

    code: Final[Literal["draft_invalid"]] = "draft_invalid"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"draft invalid: {reason}")


@dataclass(frozen=True, kw_only=True, slots=True)
class DraftItem:
    """A draft read as an item: its kind, its frontmatter ``name`` (None for a hook), its files,
    and for a hook its ``hooks`` object and its ``scripts/`` files."""

    kind: UnitKind
    name: str | None
    content: UnitContent
    hooks: HookGroups | None = None
    scripts: tuple[UnitFile, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class Destination:
    """Where a draft lands: the unit written and its content, the unit a rename removes, and the
    hook scripts to write first (hub-relative paths)."""

    unit: ItemUnit
    content: UnitContent
    removed: ItemUnit | None = None
    scripts: tuple[UnitFile, ...] = ()


class HookAt(NamedTuple):
    """A hook in its file: its event and its 1-based position among the event's hooks, as the
    catalog counts them (``hook_records``)."""

    event: str
    position: int


def read_draft_item(kind: UnitKind, files: UnitContent) -> DraftItem:
    """``files`` (a draft of ``kind``) as an item, or ``DraftInvalidError``."""
    if any(segment.startswith(".") for file in files.files for segment in file.path.split("/")):
        raise DraftInvalidError("The draft holds a hidden name")
    _refuse_file_under_file(files)
    if kind is UnitKind.SKILL:
        return DraftItem(kind=kind, name=_name_of(_main(files, SKILL_FILE)), content=files)
    if kind is UnitKind.AGENT:
        return _agent_draft(files)
    if kind is UnitKind.HOOK:
        return _hook_draft(files)
    raise DraftInvalidError("A draft is a skill, an agent or a hook")


def edit_destination(target: ItemUnit, current: UnitContent, draft: DraftItem) -> Destination:
    """Where an edit of the skill or agent ``target`` (its content on disk ``current``) lands."""
    if draft.kind is not target.kind:
        raise DraftInvalidError("The draft's kind differs from the item's")
    if target.kind is UnitKind.HOOK:
        msg = "a hook edit goes through replace_hook"
        raise ValueError(msg)
    parent, _, own = target.unit_path.rpartition("/")
    name = draft.name or ""
    if target.kind is UnitKind.SKILL:
        merged = {file.path: file for file in current.files}
        merged.update((file.path, file) for file in draft.content.files)
        content = UnitContent(files=tuple(merged[path] for path in sorted(merged)))
        _refuse_file_under_file(content)
        new_own = name
    else:
        new_own = f"{name}{_AGENT_SUFFIX}"
        content = _single(draft.content.files[0], new_own)
    if new_own == own:
        return Destination(unit=target, content=content)
    unit = ItemUnit(project=target.project, unit_path=f"{parent}/{new_own}", kind=target.kind)
    return Destination(unit=unit, content=content, removed=target)


def new_destination(
    project: str, draft: DraftItem, *, current_hooks: bytes | None = None
) -> Destination:
    """Where a new item lands in ``project``'s own plugin; a hook is merged into the plugin's
    hooks file (``current_hooks``, None when absent) and its scripts go to ``scripts/``."""
    plugin = f"{PLUGIN_FOLDER}/{project}"
    if draft.kind is UnitKind.SKILL:
        unit_path, content = f"{plugin}/{SKILLS_FOLDER}/{draft.name}", draft.content
    elif draft.kind is UnitKind.AGENT:
        own = f"{draft.name}{_AGENT_SUFFIX}"
        unit_path, content = f"{plugin}/{AGENTS_FOLDER}/{own}", _single(draft.content.files[0], own)
    else:
        merged = merge_hooks(current_hooks, draft.hooks or {})
        unit_path = f"{plugin}/{HOOKS_FOLDER}/{HOOKS_FILE}"
        content = UnitContent(files=(UnitFile(path=HOOKS_FILE, content=merged),))
    scripts = tuple(
        UnitFile(
            path=f"{plugin}/{script.path}", content=script.content, executable=script.executable
        )
        for script in draft.scripts
    )
    unit = ItemUnit(project=project, unit_path=unit_path, kind=draft.kind)
    return Destination(unit=unit, content=content, scripts=scripts)


def hook_at(*, source: str, name: str, event: str) -> HookAt:
    """Where the catalog's hook ``name`` of ``source`` (its ``<source>-<event>-<n>`` name, with
    the ``-<k>`` suffix of an event differing only by case) sits among ``event``'s hooks."""
    prefix = f"{source}-{event}-".lower()
    found = re.fullmatch(r"([1-9][0-9]*)(?:-[0-9]+)?", name.removeprefix(prefix))
    if not name.startswith(prefix) or found is None:
        msg = "not a hook name of that source and event"
        raise ValueError(msg)
    return HookAt(event=event, position=int(found.group(1)))


def replace_hook(file_json: bytes, at: HookAt, new_hooks: HookGroups) -> bytes:
    """``file_json`` with the hook ``at`` replaced by ``new_hooks`` (a hooks object's ``hooks``):
    a draft group of the hook's event and matcher takes its place, the others are added as
    ``merge_hooks`` adds them; a group or event left empty is dropped. Every other hook and key
    is kept. ``EntityNotFoundError`` when the file holds no such hook."""
    document = _hooks_document(file_json)
    hooks = _hooks_of(document)
    groups, group, entries, index = _locate(hooks, at)
    del entries[index]
    rest: dict[str, JsonValue] = {}
    spliced = False
    for event, draft_groups in copy.deepcopy(dict(new_hooks)).items():
        for draft_group in draft_groups if isinstance(draft_groups, list) else []:
            if not spliced and _splices(draft_group, event=event, at=at, group=group):
                entries[index:index] = _group_hooks(draft_group)
                spliced = True
            else:
                _append(rest, event, draft_group)
    if not entries:
        del groups[next(i for i, found in enumerate(groups) if found is group)]
    if not groups:
        del hooks[at.event]
    _add_groups(hooks, rest)
    return dump_json(document)


def merge_hooks(file_json: bytes | None, new_hooks: HookGroups) -> bytes:
    """``file_json`` (a hooks file, None when absent) with ``new_hooks``' matcher groups added
    after each event's own; every hook and key already there is kept."""
    document: dict[str, JsonValue] = {} if file_json is None else _hooks_document(file_json)
    hooks = document.setdefault(_HOOKS_KEY, {})
    if not isinstance(hooks, dict):
        raise ItemWriteRefusedError("unit_unreadable", _NOT_HOOKS_FILE)
    _add_groups(hooks, copy.deepcopy(dict(new_hooks)))
    return dump_json(document)


def _main(files: UnitContent, path: str) -> UnitFile:
    for file in files.files:
        if file.path == path:
            return file
    raise DraftInvalidError("The draft has no main file")


def _name_of(main: UnitFile) -> str:
    text = text_of(main.content)
    document = None if text is None else read_skill_document(text)
    if document is None or document.problem is not None:
        raise DraftInvalidError("The draft's main file has no readable frontmatter")
    names = [pair.value for pair in document.pairs if pair.key == _NAME_KEY]
    name = names[0] if names else None
    if not isinstance(name, str) or not _ITEM_NAME.fullmatch(name):
        raise DraftInvalidError("The draft's name is missing or not letters, digits, - or _")
    return name


def _agent_draft(files: UnitContent) -> DraftItem:
    shaped = len(files.files) == 1 and "/" not in files.files[0].path
    if not shaped or not files.files[0].path.endswith(_AGENT_SUFFIX):
        raise DraftInvalidError("An agent draft is one .md file")
    return DraftItem(kind=UnitKind.AGENT, name=_name_of(files.files[0]), content=files)


def _hook_draft(files: UnitContent) -> DraftItem:
    main = _main(files, HOOKS_FILE)
    scripts = tuple(file for file in files.files if file is not main)
    for script in scripts:
        folder, _, name = script.path.partition("/")
        if folder != _SCRIPTS_FOLDER or not name or "/" in name:
            raise DraftInvalidError("A hook draft holds hooks.json and scripts/<file> only")
    fold = hook_records(None, None, {_DRAFT_SOURCE: main.content}, enabled={}, marketplace=None)
    if fold.notices or fold.truncated or not fold.records:
        raise DraftInvalidError("The draft's hooks.json is not a hooks object")
    # The fold read this same object, so its hooks are there.
    hooks = _hooks_of(_hooks_document(main.content))
    return DraftItem(kind=UnitKind.HOOK, name=None, content=files, hooks=hooks, scripts=scripts)


def _refuse_file_under_file(files: UnitContent) -> None:
    """Refuse a file whose path is a folder of another file's (``refs`` and ``refs/r.md``)."""
    paths = {file.path for file in files.files}
    for path in paths:
        segments = path.split("/")
        if any("/".join(segments[:depth]) in paths for depth in range(1, len(segments))):
            raise DraftInvalidError("A file of the draft sits where a folder is")


def _single(file: UnitFile, name: str) -> UnitContent:
    return UnitContent(
        files=(UnitFile(path=name, content=file.content, executable=file.executable),)
    )


def _hooks_document(file_json: bytes) -> dict[str, JsonValue]:
    try:
        document = load_json_bytes(file_json)
    except InvalidJsonError, RecursionError:
        raise ItemWriteRefusedError("unit_unreadable", _NOT_HOOKS_FILE) from None
    if not isinstance(document, dict):
        raise ItemWriteRefusedError("unit_unreadable", _NOT_HOOKS_FILE)
    return document


def _hooks_of(document: dict[str, JsonValue]) -> dict[str, JsonValue]:
    hooks = document.get(_HOOKS_KEY)
    if not isinstance(hooks, dict):
        raise ItemWriteRefusedError("unit_unreadable", _NOT_HOOKS_FILE)
    return hooks


type _Located = tuple[list[JsonValue], dict[str, JsonValue], list[JsonValue], int]


def _locate(hooks: dict[str, JsonValue], at: HookAt) -> _Located:
    """The event's groups, the matcher group holding the hook ``at``, that group's hooks and the
    hook's index there, counted as the catalog counts (a group without a list of hooks, or a
    hook that is no object, is not counted)."""
    groups = hooks.get(at.event)
    position = 0
    for group in groups if isinstance(groups, list) else []:
        entries = group.get(_HOOKS_KEY) if isinstance(group, dict) else None
        if not isinstance(group, dict) or not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                position += 1
                if position == at.position and isinstance(groups, list):
                    return groups, group, entries, index
    raise EntityNotFoundError(entity="hook", entity_id=f"{at.event}-{at.position}")


def _splices(
    draft_group: JsonValue, *, event: str, at: HookAt, group: dict[str, JsonValue]
) -> bool:
    """Whether ``draft_group`` takes the replaced hook's place: same event and matcher, and
    nothing a splice would lose."""
    return (
        event == at.event
        and isinstance(draft_group, dict)
        and draft_group.keys() <= _SPLICED_KEYS
        and draft_group.get(_MATCHER_KEY) == group.get(_MATCHER_KEY)
    )


def _group_hooks(draft_group: JsonValue) -> list[JsonValue]:
    entries = draft_group.get(_HOOKS_KEY) if isinstance(draft_group, dict) else None
    return entries if isinstance(entries, list) else []


def _append(groups_by_event: dict[str, JsonValue], event: str, group: JsonValue) -> None:
    groups = groups_by_event.setdefault(event, [])
    if isinstance(groups, list):
        groups.append(group)


def _add_groups(hooks: dict[str, JsonValue], new_hooks: dict[str, JsonValue]) -> None:
    for event, groups in new_hooks.items():
        existing = hooks.setdefault(event, [])
        if not isinstance(existing, list):
            raise ItemWriteRefusedError("unit_unreadable", _NOT_HOOKS_FILE)
        existing.extend(groups if isinstance(groups, list) else [])
