"""``PublishDraft``: land a Studio draft in the hub (AGH-295, D10, D19, D21, D24, S4, S5, A5, A7,
A8, A12-A18, A20; AC-295.11-16).

The draft is read whole (``HubItemWriter.read_draft``) and as an item of its kind
(``read_draft_item``). An edit names its target, resolved to its unit as the history reads
resolve it (an unknown item is ``EntityNotFoundError``); the draft's kind must be the target's
(``DraftInvalidError``). A new item (no target) lands in the project's own plugin; a skill or
agent whose name the catalog already has in that kind (any source, case aside; the fold's item
names only, without the catalog read's capture and usage) is ``item_exists``. A skill or agent's
destination that the listing holds already (a rename onto a sibling, a new item's folder without
``SKILL.md``) is ``item_exists`` too, and so is one the disk holds when the write reads it.

The shared step (``RecordAndWrite.publish``) then holds every unit touched under its one lock:
the target, a rename's new unit, a new item's destination. A draft that a version of the project
already names as its ``publish`` is spent (A20): the step answers ``draft_already_published``
before it reads anything, and nothing is written, recorded or removed; the draft stays for the
user to discard. Otherwise the step records each unit's disk content first, places the draft from
what it read (``edit_destination``, ``replace_hook`` for a hook, ``new_destination``), writes (a
new hook's scripts first; a renamed skill carries the old folder's hidden entries, then the old
unit is removed) and records a ``publish`` naming the draft. A hook edit's place in its file
(``hook_at``) is read from the file the step read under its lock, so the hook replaced is the one
the recorded content names. With no version naming the draft (a first publish, or a retry whose
first write stored none: a secret, too large, a lost race, ``written_not_recorded``), a draft
that moves its hook into a file already holding the draft's groups is refused (``item_exists``,
A12, in words that claim no earlier publish, A17) and nothing is written, while one that splices
in place is kept as it is when the file already holds it (A16, ``replace_hook``). A hook edit
carrying scripts is ``DraftInvalidError`` (A14): scripts land only with a new hook. A merge into
a unit past the read bounds is ``unit_unreadable`` (A13). A retried rename whose old item is gone
is an unknown item, and a retried new item whose first write stored no version is
``item_exists`` (A12). An item gone before the lock is an unknown item of its unit's kind.

After the step, the draft is removed, also when nothing changed (A7); a removal that fails raises
``DraftNotRemovedError`` carrying the step's answer: what was written stays written, and the kept
draft is spent if a ``publish`` was recorded. No message names a path.
"""

from collections.abc import Collection, Iterator
from typing import Final, Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadUnit
from agent_hub.core.item_versions.hub_item_writer import (
    HubItemWriteError,
    HubItemWriter,
    ItemWriteRefusedError,
)
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.item_version_ports import (
    ItemWriteResult,
    ToolkitRef,
    ToolkitUnits,
)
from agent_hub.core.item_versions.publish_rules import (
    Destination,
    DraftInvalidError,
    DraftItem,
    HookAt,
    edit_destination,
    holds_moved_hook,
    hook_at,
    new_destination,
    read_draft_item,
    replace_hook,
)
from agent_hub.core.item_versions.read_item_versions import marked_unit
from agent_hub.core.item_versions.record_and_write import RecordAndWrite, UnitReads
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_hooks import hook_records
from agent_hub.core.skills.skill_sources import PROJECT_SETTINGS_PATH, SETTINGS_PATH
from agent_hub.core.skills.skill_view import ItemKind, item_id

DRAFT_NOT_REMOVED: Final = "Published; the draft is still there. Discard it."
_SKILL_ENTITY: Final = "skill"
_PROJECT_ENTITY: Final = "project"
_TOO_LARGE_TO_MERGE: Final = "The item on disk is too large to merge the draft into"
_SCRIPTS_IN_EDIT: Final = "A hook's scripts land only with a new hook"
# A17: the server cannot tell a retry from a first publish here, so the answer claims neither.
_MOVED_HOOK_HELD: Final = "The hooks file already holds this draft's hooks"


class DraftNotRemovedError(AgentHubError):
    """Published (``result``), but the draft folder could not be removed (500
    ``draft_not_removed``); the user discards it (a recorded ``publish`` spends it, A20)."""

    code: Final = "draft_not_removed"

    def __init__(self, result: ItemWriteResult) -> None:
        self.result = result
        self.reason = DRAFT_NOT_REMOVED
        super().__init__(f"draft not removed: {DRAFT_NOT_REMOVED}")


class PublishCatalog(Protocol):
    """The reads a Publish needs besides the item's unit (``HubReadModels`` answers them)."""

    def project_hubs(self) -> Iterator[tuple[str, str]]:
        """Each project and its hub folder."""
        ...

    def skill_item_names(self, project: str) -> frozenset[tuple[ItemKind, str]]:
        """The kind and name of each of the project's items, from the fold alone (no capture,
        no usage)."""
        ...


class PublishDraft:
    """Publishes a Studio draft (see the module doc)."""

    def __init__(
        self,
        step: RecordAndWrite,
        *,
        writer: HubItemWriter,
        reader: HubFileReader,
        toolkit_units: ToolkitUnits,
        catalog: PublishCatalog,
    ) -> None:
        self._step = step
        self._writer = writer
        self._reader = reader
        self._toolkit = toolkit_units
        self._catalog = catalog

    def publish(
        self, project: str, draft_id: str, target: ToolkitRef | None, *, confirm_managed: bool
    ) -> ItemWriteResult:
        """Land the draft ``draft_id`` of ``project`` on ``target`` (None: a new item), then
        remove the draft."""
        if target is None:
            hub_path = self._hub_of(project)
            units, place = self._new(project, hub_path, self._draft(hub_path, draft_id))
        else:
            marked = marked_unit(target, toolkit_units=self._toolkit, workflow_units=_NO_WORKFLOWS)
            hub_path = marked.hub_path
            draft = self._draft(hub_path, draft_id)
            if draft.kind is not marked.unit.kind:
                raise DraftInvalidError("The draft's kind differs from the item's")
            units, place = self._edit(hub_path, target, unit=marked.unit, draft=draft)
        result = self._step.publish(
            hub_path, units, place, confirm_managed=confirm_managed, draft_id=draft_id
        )
        try:
            self._writer.remove_draft(hub_path, draft_id)
        except (HubItemWriteError, ItemWriteRefusedError) as failed:
            raise DraftNotRemovedError(result) from failed
        return result

    def _draft(self, hub_path: str, draft_id: str) -> DraftItem:
        files = self._writer.read_draft(hub_path, draft_id)
        return read_draft_item(files.kind, files.content)

    def _hub_of(self, project: str) -> str:
        for name, hub_path in self._catalog.project_hubs():
            if name == project:
                return hub_path
        raise EntityNotFoundError(entity=_PROJECT_ENTITY, entity_id=project)

    def _listed(self, hub_path: str) -> frozenset[str]:
        """Every path the hub's listing holds, and every folder above one."""
        listed: set[str] = set()
        for entry in self._reader.skill_sources(hub_path).files:
            segments = entry.path.split("/")
            listed.update("/".join(segments[:depth]) for depth in range(1, len(segments) + 1))
        return frozenset(listed)

    def _edit(
        self, hub_path: str, target: ToolkitRef, *, unit: ItemUnit, draft: DraftItem
    ) -> tuple[list[ItemUnit], _Place]:
        if unit.kind is UnitKind.HOOK:
            if draft.scripts:
                raise DraftInvalidError(_SCRIPTS_IN_EDIT)
            return [unit], _HookEdit(target, unit=unit, draft=draft)
        listed = self._listed(hub_path) - {unit.unit_path}
        # Where it lands depends only on the draft's name: the content read here is a stand-in.
        # A destination the listing holds is refused under the lock.
        planned = edit_destination(unit, draft.content, draft, existing=())
        renamed = None if planned.removed is None else planned.unit
        units = [unit] if renamed is None else [unit, renamed]
        return units, _Edit(unit, draft, listed)

    def _new(self, project: str, hub_path: str, draft: DraftItem) -> tuple[list[ItemUnit], _Place]:
        planned = new_destination(project, draft)
        taken = False
        if draft.kind is not UnitKind.HOOK:
            kind = ItemKind(draft.kind.value)
            name = (draft.name or "").casefold()
            names = self._catalog.skill_item_names(project)
            listed = {path.casefold() for path in self._listed(hub_path)}
            taken = planned.unit.unit_path.casefold() in listed or any(
                item_kind is kind and item_name.casefold() == name for item_kind, item_name in names
            )
        return [planned.unit], _New(project, draft, taken=taken)


class _Place(Protocol):
    def __call__(self, reads: UnitReads) -> Destination: ...


class _Edit:
    """Where a skill or agent edit lands, from its unit on disk."""

    def __init__(self, unit: ItemUnit, draft: DraftItem, listed: Collection[str]) -> None:
        self._unit = unit
        self._draft = draft
        self._listed = listed

    def __call__(self, reads: UnitReads) -> Destination:
        current = _current(reads, self._unit, merged=self._unit.kind is UnitKind.SKILL)
        destination = edit_destination(self._unit, current, self._draft, existing=self._listed)
        if destination.removed is not None and not _missing(reads, destination.unit):
            raise ItemWriteRefusedError("item_exists")
        return destination


class _HookEdit:
    """Where a hook edit lands: its file with that one hook replaced."""

    def __init__(self, target: ToolkitRef, *, unit: ItemUnit, draft: DraftItem) -> None:
        self._target = target
        self._unit = unit
        self._draft = draft

    def __call__(self, reads: UnitReads) -> Destination:
        current = _current(reads, self._unit, merged=True)
        file = current.files[0]
        hooks = self._draft.hooks or {}
        at = _hook_in(self._unit, self._target, file.content)
        if holds_moved_hook(file.content, at, hooks):
            raise ItemWriteRefusedError("item_exists", _MOVED_HOOK_HELD)
        written = replace_hook(file.content, at, hooks)
        content = UnitContent(
            files=(UnitFile(path=file.path, content=written, executable=file.executable),)
        )
        return Destination(unit=self._unit, content=content)


class _New:
    """Where a new item lands in the project's plugin; a hook merged into its hooks file."""

    def __init__(self, project: str, draft: DraftItem, *, taken: bool) -> None:
        self._project = project
        self._draft = draft
        self._taken = taken

    def __call__(self, reads: UnitReads) -> Destination:
        planned = new_destination(self._project, self._draft)
        if self._draft.kind is not UnitKind.HOOK:
            if self._taken or not _missing(reads, planned.unit):
                raise ItemWriteRefusedError("item_exists")
            return planned
        current = reads[planned.unit.unit_path]
        if isinstance(current, UnreadUnit) and current.kind != "missing":
            raise ItemWriteRefusedError("unit_unreadable", _TOO_LARGE_TO_MERGE)
        hooks = current.files[0].content if isinstance(current, UnitContent) else None
        return new_destination(self._project, self._draft, current_hooks=hooks)


class _NoWorkflows:
    """A Publish names a Toolkit item only; it never resolves a workflow."""

    def marked_workflow_unit(self, project: str, name: str) -> None:
        del project, name


_NO_WORKFLOWS: Final = _NoWorkflows()


def _current(reads: UnitReads, unit: ItemUnit, *, merged: bool) -> UnitContent:
    """The unit's content on disk; a unit gone since the listing is an unknown item, one too
    large to read whole is refused when the draft is merged into it."""
    read = reads[unit.unit_path]
    if isinstance(read, UnitContent):
        return read
    if read.kind == "missing":
        entity = unit.kind.value
        raise EntityNotFoundError(entity=entity, entity_id=unit.unit_path.rsplit("/")[-1])
    if merged:
        raise ItemWriteRefusedError("unit_unreadable", _TOO_LARGE_TO_MERGE)
    return UnitContent(files=())


def _missing(reads: UnitReads, unit: ItemUnit) -> bool:
    read = reads[unit.unit_path]
    return isinstance(read, UnreadUnit) and read.kind == "missing"


def _hook_in(unit: ItemUnit, target: ToolkitRef, file_json: bytes) -> HookAt:
    """Where the hook ``target`` sits in its file's content ``file_json``, named as the catalog
    names it (a hook's name depends only on its own file); an unknown item when it holds none."""
    if unit.unit_path == SETTINGS_PATH:
        fold = hook_records(file_json, None, {}, enabled={}, marketplace=None)
    elif unit.unit_path == PROJECT_SETTINGS_PATH:
        fold = hook_records(None, file_json, {}, enabled={}, marketplace=None)
    else:
        plugin = unit.unit_path.split("/")[1]
        fold = hook_records(None, None, {plugin: file_json}, enabled={}, marketplace=None)
    for record in fold.records:
        if record.source == target.source and record.name == target.name:
            return hook_at(source=target.source, name=target.name, event=record.facts.event)
    raise EntityNotFoundError(
        entity=_SKILL_ENTITY, entity_id=item_id(target.kind, target.source, target.name)
    )
