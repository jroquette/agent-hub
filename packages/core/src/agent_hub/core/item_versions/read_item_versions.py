"""``ReadItemVersions``: an item's history and one version's content (AGH-295, S6, S7, S8, S10).

A list first captures the item's one unit through the app's ``CaptureItemVersions`` with the
mark the catalog and detail use, so the memo is shared and ``state`` is what the disk holds now
(a warm list reads no unit). It pages the unit's versions newest first: ``limit`` of them below
the cursor's ``seq``; ``seq`` is gap-free and versions are append-only, so a page never repeats
or skips one. A version is answered only within the item's own unit. An unknown project or item
is ``EntityNotFoundError`` from the unit ports; an item with no unit (a link, a built-in) has no
history (entity ``item history``), and an id outside the unit is entity ``item version``.
"""

from typing import Final

from agent_hub.core.hubs.hub_registry import HubFileReader
from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions, UnitState
from agent_hub.core.item_versions.item_units import is_managed
from agent_hub.core.item_versions.item_version import ItemVersionMeta, UnitKind
from agent_hub.core.item_versions.item_version_ports import (
    ItemRef,
    ItemVersionContent,
    ItemVersionPage,
    ItemVersionView,
    MarkedUnit,
    ToolkitRef,
    ToolkitUnits,
    VersionFileView,
    WorkflowUnits,
)
from agent_hub.core.item_versions.unit_content import decode
from agent_hub.core.item_versions.version_store import ItemVersionStore
from agent_hub.core.readmodels.cursor import (
    Cursor,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_view import item_id

HISTORY_ENTITY: Final = "item history"
VERSION_ENTITY: Final = "item version"
# The largest seq a store can hold (SQLite's signed 64-bit integer).
MAX_SEQ: Final = 2**63 - 1


class ReadItemVersions:
    """``ItemVersionReads`` over the store, the hub files and the Toolkit and workflow units."""

    def __init__(
        self,
        store: ItemVersionStore,
        *,
        reader: HubFileReader,
        toolkit_units: ToolkitUnits,
        workflow_units: WorkflowUnits,
        capture: CaptureItemVersions,
    ) -> None:
        self._store = store
        self._reader = reader
        self._toolkit = toolkit_units
        self._workflows = workflow_units
        self._capture = capture

    def list(self, ref: ItemRef, *, limit: int, cursor: str | None) -> ItemVersionPage:
        """The item's versions newest first (see the module doc)."""
        before = None if cursor is None else _before_seq(cursor)
        hub_path, unit, mark, shared_by = self._marked(ref)
        states = self._capture.capture(unit.project, hub_path, [(unit, mark)])
        # Not settled now: the unit vanished, or its append lost every race (left for the next
        # read); neither is a secret or a bound, so the disk is shown as readable.
        state = states.get(unit.unit_path, UnitState.OK)
        versions = self._store.page(unit.project, unit.unit_path, limit=limit, before_seq=before)
        last = self._store.last(unit.project, unit.unit_path)
        return ItemVersionPage(
            items=tuple(_view(version) for version in versions),
            next_cursor=_next_cursor(versions, limit),
            total_estimate=0 if last is None else last.seq,
            state=state,
            managed=is_managed(self._reader.read_lock(hub_path), unit),
            unit_path=unit.unit_path,
            unit_kind=unit.kind,
            shared_by=shared_by,
        )

    def get(self, ref: ItemRef, version_id: str) -> ItemVersionContent:
        """One version of the item's own unit, with its files' texts."""
        unit = self._marked(ref).unit
        version = self._store.get(unit.project, unit.unit_path, version_id)
        if version is None:
            raise EntityNotFoundError(entity=VERSION_ENTITY, entity_id=version_id)
        folder = unit.kind is UnitKind.SKILL
        content = decode(version.content, folder=folder, name=unit.unit_path.rsplit("/", 1)[-1])
        files = tuple(
            VersionFileView(
                path=file.path,
                executable=file.executable,
                size=len(file.content),
                text=_text_of(file.content),
            )
            for file in content.files
        )
        return ItemVersionContent(id=version.id, unit_kind=unit.kind, files=files)

    def _marked(self, ref: ItemRef) -> MarkedUnit:
        if isinstance(ref, ToolkitRef):
            marked = self._toolkit.marked_skill_unit(
                ref.project, kind=ref.kind, source=ref.source, name=ref.name
            )
            named = item_id(ref.kind, ref.source, ref.name)
        else:
            marked = self._workflows.marked_workflow_unit(ref.project, ref.name)
            named = ref.name
        if marked is None:
            raise EntityNotFoundError(entity=HISTORY_ENTITY, entity_id=f"{ref.project}/{named}")
        return marked


def _view(version: ItemVersionMeta) -> ItemVersionView:
    return ItemVersionView(
        id=version.id,
        origin=version.origin,
        first=version.first,
        author=version.author,
        recorded_at=version.recorded_at,
        content_hash=version.content_hash,
        size=version.size,
        restored_from=version.restored_from,
        draft_id=version.draft_id,
    )


def _next_cursor(versions: tuple[ItemVersionMeta, ...], limit: int) -> str | None:
    if len(versions) < limit or not versions or versions[-1].seq <= 1:
        return None
    last = versions[-1]
    return encode_cursor(Cursor(hwm=0, key=(last.seq,), id=last.id))


def _before_seq(text: str) -> int:
    key = decode_cursor(text).key
    if len(key) != 1 or not isinstance(key[0], int) or not 1 <= key[0] <= MAX_SEQ:
        msg = "invalid cursor: it was not written by this list"
        raise InvalidCursorError(msg)
    return key[0]


def _text_of(content: bytes) -> str | None:
    if b"\x00" in content:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
