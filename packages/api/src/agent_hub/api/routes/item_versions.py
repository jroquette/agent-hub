"""An item's version history (AGH-295, S7): the versions of a Toolkit item's or a hub workflow's
unit, newest first, one version's content, and its restore. Each route is one call to the
history reads or writes; the list captures the unit first, in agent-hub's database, never in
the hub.

A ``version_id`` that is not a UUID, and the item segments outside their patterns, answer 400
before anything is read; an unknown project or item, an item without a unit (a link, a
built-in) and a version of another unit answer 404.

A restore (D4, D12, D13) is the one route that writes into a hub's working tree: the strict
rule and the launch cookie gate it before routing (``local_security``, ``session_access``; 409
``hub_read_only`` in the container), and the shared write step's refusals answer 409 with a
``code`` (``rfc9457``). It answers ``{changed, versioned, reason, version}``.

The Studio's Publish (D10, S5, S7) is the other: ``POST .../skills/drafts/{draft_id}/publish``
lands the draft ``.hub-drafts/<draft_id>/`` on its ``target`` (``null``: a new item) through
the same step, behind the same gates, and answers the same shape. A ``draft_id`` outside
``(skill|agent|hook)-[a-z0-9]{6}`` answers 400 and a body outside its shape 422, before
anything is read; the draft's own refusals answer 404, 409, 413 or 422 (``rfc9457``).
"""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import ItemVersionReadsDep, ItemVersionWritesDep
from agent_hub.api.routes.skills import NamePath, ProjectPath, SourcePath
from agent_hub.api.routes.workflows import NamePath as WorkflowNamePath
from agent_hub.api.schemas import (
    DEFAULT_LIMIT,
    ITEM_WRITE_RESPONSES,
    PROBLEM_RESPONSES,
    PUBLISH_RESPONSES,
    CursorParam,
    LimitParam,
    PublishDraftBody,
    RestoreVersionBody,
)
from agent_hub.core.events.stored_event import UUID_TEXT_PATTERN
from agent_hub.core.item_versions.item_version import DRAFT_ID
from agent_hub.core.item_versions.item_version_ports import (
    ItemVersionContent,
    ItemVersionPage,
    ItemWriteResult,
    ToolkitRef,
    WorkflowRef,
)
from agent_hub.core.skills.skill_view import ItemKind

router = APIRouter(tags=["item versions"], responses=PROBLEM_RESPONSES)

VersionIdPath = Annotated[str, Path(pattern=UUID_TEXT_PATTERN)]
DraftIdPath = Annotated[str, Path(pattern=DRAFT_ID)]
SKILL_ITEM = "/projects/{project}/skills/{kind}/{source}/{name}"
WORKFLOW_ITEM = "/workflows/{project}/{name}"


@router.get(f"{SKILL_ITEM}/versions")
def list_skill_versions(  # noqa: PLR0913 - the item's id and the page, all keyword-only
    *,
    project: ProjectPath,
    kind: ItemKind,
    source: SourcePath,
    name: NamePath,
    reads: ItemVersionReadsDep,
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> ItemVersionPage:
    """The versions of the item's unit, newest first, and what its disk holds now."""
    ref = ToolkitRef(project=project, kind=kind, source=source, name=name)
    return reads.list(ref, limit=limit, cursor=cursor)


@router.get(f"{SKILL_ITEM}/versions/{{version_id}}")
def get_skill_version(  # noqa: PLR0913 - the item's id and the version's, all keyword-only
    *,
    project: ProjectPath,
    kind: ItemKind,
    source: SourcePath,
    name: NamePath,
    version_id: VersionIdPath,
    reads: ItemVersionReadsDep,
) -> ItemVersionContent:
    """One version of the item's unit: its files, their texts and executable bits."""
    ref = ToolkitRef(project=project, kind=kind, source=source, name=name)
    return reads.get(ref, version_id)


@router.get(f"{WORKFLOW_ITEM}/versions")
def list_workflow_versions(
    *,
    project: WorkflowNamePath,
    name: WorkflowNamePath,
    reads: ItemVersionReadsDep,
    limit: LimitParam = DEFAULT_LIMIT,
    cursor: CursorParam = None,
) -> ItemVersionPage:
    """The versions of the hub workflow's file, newest first, and what the disk holds now."""
    return reads.list(WorkflowRef(project=project, name=name), limit=limit, cursor=cursor)


@router.get(f"{WORKFLOW_ITEM}/versions/{{version_id}}")
def get_workflow_version(
    *,
    project: WorkflowNamePath,
    name: WorkflowNamePath,
    version_id: VersionIdPath,
    reads: ItemVersionReadsDep,
) -> ItemVersionContent:
    """One version of the hub workflow's file."""
    return reads.get(WorkflowRef(project=project, name=name), version_id)


@router.post(f"{SKILL_ITEM}/versions/{{version_id}}/restore", responses=ITEM_WRITE_RESPONSES)
def restore_skill_version(  # noqa: PLR0913 - the item's id, the version's and the body
    *,
    project: ProjectPath,
    kind: ItemKind,
    source: SourcePath,
    name: NamePath,
    version_id: VersionIdPath,
    body: RestoreVersionBody,
    writes: ItemVersionWritesDep,
) -> ItemWriteResult:
    """Write the version back into the hub and record a ``restore`` version naming it."""
    ref = ToolkitRef(project=project, kind=kind, source=source, name=name)
    return writes.restore(ref, version_id, confirm_managed=body.confirm_managed)


@router.post(f"{WORKFLOW_ITEM}/versions/{{version_id}}/restore", responses=ITEM_WRITE_RESPONSES)
def restore_workflow_version(
    *,
    project: WorkflowNamePath,
    name: WorkflowNamePath,
    version_id: VersionIdPath,
    body: RestoreVersionBody,
    writes: ItemVersionWritesDep,
) -> ItemWriteResult:
    """Write the version back into the hub workflow's file and record a ``restore`` version."""
    ref = WorkflowRef(project=project, name=name)
    return writes.restore(ref, version_id, confirm_managed=body.confirm_managed)


@router.post("/projects/{project}/skills/drafts/{draft_id}/publish", responses=PUBLISH_RESPONSES)
def publish_draft(
    *,
    project: ProjectPath,
    draft_id: DraftIdPath,
    body: PublishDraftBody,
    writes: ItemVersionWritesDep,
) -> ItemWriteResult:
    """Land the Studio draft on its target (``null``: a new item), record a ``publish``
    version naming the draft, then remove the draft."""
    target = body.target
    ref = (
        None
        if target is None
        else ToolkitRef(project=project, kind=target.kind, source=target.source, name=target.name)
    )
    return writes.publish(project, draft_id, ref, confirm_managed=body.confirm_managed)
