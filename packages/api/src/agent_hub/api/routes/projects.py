"""``/projects``: Portfolio cards and the Project overview."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from agent_hub.api.dependencies import HubReadModelsDep
from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES
from agent_hub.core.brain.brain_note import BrainNote, BrainTree
from agent_hub.core.brain.brain_path import MAX_PATH_CHARS
from agent_hub.core.projects.project_views import (
    ProjectDetail,
    ProjectNow,
    ProjectSummary,
    RepoView,
)
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["projects"], responses=PROBLEM_RESPONSES)

ProjectPath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]
NotePathParam = Annotated[str, Query(min_length=1, max_length=MAX_PATH_CHARS)]


@router.get("/projects")
def list_projects(models: HubReadModelsDep) -> Page[ProjectSummary]:
    """A card per registered project."""
    return models.list_projects()


@router.get("/projects/{project}")
def get_project(project: ProjectPath, models: HubReadModelsDep) -> ProjectDetail:
    """The Project overview header."""
    return models.get_project(project)


@router.get("/projects/{project}/now")
def get_project_now(project: ProjectPath, models: HubReadModelsDep) -> ProjectNow:
    """The project's ``brain/now.md``."""
    return models.project_now(project)


@router.get("/projects/{project}/repos")
def list_project_repos(project: ProjectPath, models: HubReadModelsDep) -> Page[RepoView]:
    """The project's repos."""
    return models.project_repos(project)


@router.get("/projects/{project}/brain")
def get_brain_tree(project: ProjectPath, models: HubReadModelsDep) -> BrainTree:
    """The ``.md`` notes of the project's hub brain (``auto/`` excluded)."""
    del project, models
    raise NotImplementedInBuildError("get_brain_tree")


@router.get("/projects/{project}/brain/note")
def get_brain_note(
    project: ProjectPath, path: NotePathParam, models: HubReadModelsDep
) -> BrainNote:
    """One brain note by its path under ``brain/``: frontmatter, markdown body and size."""
    del project, path, models
    raise NotImplementedInBuildError("get_brain_note")
