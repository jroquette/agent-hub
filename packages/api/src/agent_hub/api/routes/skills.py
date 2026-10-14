"""``/projects/{project}/skills``: the Skills tab's catalog, an item's detail and a bundled
file's text (AGH-164). Read-only: GET only, each route one call to the hub read models.

Items are addressed by ``kind/source/name`` and bundled files by a server-issued id, never by a
client path (D2, L5): a segment outside its pattern answers 400 before anything is read.
"""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import HubReadModelsDep
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES
from agent_hub.core.skills.skill_view import (
    FILE_ID,
    ITEM_NAME,
    BundledFileText,
    ItemKind,
    SkillCatalog,
    SkillDetail,
)

router = APIRouter(tags=["skills"], responses=PROBLEM_RESPONSES)

ProjectPath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]
SourcePath = Annotated[str, Path(pattern=ITEM_NAME)]
NamePath = Annotated[str, Path(pattern=ITEM_NAME)]
FileIdPath = Annotated[str, Path(pattern=FILE_ID)]


@router.get("/projects/{project}/skills")
def get_skill_catalog(project: ProjectPath, models: HubReadModelsDep) -> SkillCatalog:
    """The project's skills, agents and hooks, with 30-day usage and third-party plugins."""
    return models.skill_catalog(project)


@router.get("/projects/{project}/skills/{kind}/{source}/{name}")
def get_skill_detail(
    *,
    project: ProjectPath,
    kind: ItemKind,
    source: SourcePath,
    name: NamePath,
    models: HubReadModelsDep,
) -> SkillDetail:
    """One skill, agent or hook by its id: header fields, text, structure, relations, files."""
    return models.skill_detail(project, kind=kind, source=source, name=name)


@router.get("/projects/{project}/skills/{kind}/{source}/{name}/files/{file_id}")
def get_skill_file(
    *,
    project: ProjectPath,
    kind: ItemKind,
    source: SourcePath,
    name: NamePath,
    file_id: FileIdPath,
    models: HubReadModelsDep,
) -> BundledFileText:
    """One bundled file of a skill by the id its detail issued; its text is inert."""
    return models.skill_file(project, kind=kind, source=source, name=name, file_id=file_id)
