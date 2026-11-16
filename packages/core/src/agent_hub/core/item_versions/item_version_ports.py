"""The history reads' port, the ports it reads units through, and what it answers (AGH-295, S7).

An item is named as the routes name it: a Toolkit item by ``kind/source/name`` in a project, a
hub workflow by its name in a project. ``ToolkitUnits`` and ``WorkflowUnits`` give the item's
unit with the stat mark the catalog and detail reads capture it under (so the capture memo is
shared), the hub it lives in and how many items share it; an unknown project or item is
``EntityNotFoundError``, a known item with no unit (a link, a built-in) is None.
"""

from typing import Literal, NamedTuple, Protocol

from pydantic import Field

from agent_hub.core.item_versions.capture_item_versions import UnitMark, UnitState
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import (
    DRAFT_ID,
    ItemVersionMeta,
    UnitKind,
    VersionAuthor,
    VersionOrigin,
)
from agent_hub.core.readmodels.page import MAX_CURSOR_CHARS
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel
from agent_hub.core.skills.skill_view import ItemKind


class ToolkitRef(ViewModel):
    """A Toolkit item of a project, by its id's parts."""

    project: str = Field(min_length=1)
    kind: ItemKind
    source: str = Field(min_length=1)
    name: str = Field(min_length=1)


class WorkflowRef(ViewModel):
    """A workflow of a project's hub, by name."""

    project: str = Field(min_length=1)
    name: str = Field(min_length=1)


type ItemRef = ToolkitRef | WorkflowRef


class MarkedUnit(NamedTuple):
    """An item's unit, its capture mark, the hub folder it is read from and the number of items
    it holds (the hooks of one file share it)."""

    hub_path: str
    unit: ItemUnit
    mark: UnitMark
    shared_by: int


class ToolkitUnits(Protocol):
    def marked_skill_unit(
        self, project: str, *, kind: ItemKind, source: str, name: str
    ) -> MarkedUnit | None:
        """The item's unit and mark, or None when it has none; reads no unit."""
        ...


class WorkflowUnits(Protocol):
    def marked_workflow_unit(self, project: str, name: str) -> MarkedUnit | None:
        """The workflow's unit and mark, or None for a built-in; reads no unit."""
        ...


class ItemVersionView(ViewModel):
    """One version as the history lists it (``author`` None for ``external``, D11)."""

    id: str
    origin: VersionOrigin
    first: bool
    author: VersionAuthor | None
    recorded_at: ApiTimestamp
    content_hash: str
    size: int
    restored_from: str | None
    draft_id: str | None = Field(default=None, pattern=DRAFT_ID)


def version_view(version: ItemVersionMeta) -> ItemVersionView:
    """``version`` as the history lists it."""
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


class ItemVersionPage(ViewModel):
    """A page of a unit's versions, newest first, with what the disk holds now: ``state`` (S8,
    S10, A1), ``managed`` (A4), the unit and how many items share it."""

    items: tuple[ItemVersionView, ...]
    next_cursor: str | None = Field(default=None, max_length=MAX_CURSOR_CHARS)
    total_estimate: int = Field(ge=0)
    state: UnitState
    managed: bool
    unit_path: str
    unit_kind: UnitKind
    shared_by: int = Field(ge=1)


class VersionFileView(ViewModel):
    """One file of a version: ``text`` is None for a binary file (a NUL, or not UTF-8)."""

    path: str
    executable: bool
    size: int = Field(ge=0)
    text: str | None


class ItemVersionContent(ViewModel):
    """A version's content: a file unit's one file, or a folder's files in path order (S6)."""

    id: str
    unit_kind: UnitKind
    files: tuple[VersionFileView, ...]


class ItemVersionReads(Protocol):
    """The history routes' reads (``GET .../versions`` and ``.../versions/{version_id}``)."""

    def list(self, ref: ItemRef, *, limit: int, cursor: str | None) -> ItemVersionPage:
        """The item's versions newest first, after capturing its unit."""
        ...

    def get(self, ref: ItemRef, version_id: str) -> ItemVersionContent:
        """One version of the item's own unit; ``EntityNotFoundError`` else."""
        ...


# Why a written unit was not versioned (A2): a secret match, past the bounds, or only a new
# hook's scripts were written (A13).
type UnversionedReason = Literal["secret", "too_large", "script_only"]


class ItemWriteResult(ViewModel):
    """What a Publish or Restore did: ``changed`` False when the content was equal (nothing
    written or recorded, D12); ``versioned`` False with its ``reason`` when the written content
    was not stored (D9, A2); ``version`` the version recorded."""

    changed: bool
    versioned: bool
    reason: UnversionedReason | None
    version: ItemVersionView | None


class ItemVersionWrites(Protocol):
    """The item routes' writes: ``POST .../versions/{version_id}/restore`` and
    ``POST .../skills/drafts/{draft_id}/publish``."""

    def restore(self, ref: ItemRef, version_id: str, *, confirm_managed: bool) -> ItemWriteResult:
        """Write the version of the item's own unit back and record a ``restore`` version."""
        ...

    def publish(
        self, project: str, draft_id: str, target: ToolkitRef | None, *, confirm_managed: bool
    ) -> ItemWriteResult:
        """Land the draft on ``target`` (None: a new item), record a ``publish`` version naming
        the draft, then remove the draft."""
        ...

    def write_file(self, hub_path: str, unit: ItemUnit, content: bytes) -> ItemWriteResult:
        """Make the file unit ``unit`` hold ``content`` (the scenario builder's save), through
        the shared write step, and record a ``publish`` version of it."""
        ...
