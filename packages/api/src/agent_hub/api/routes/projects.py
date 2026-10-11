"""``/projects``: Portfolio cards and the Project overview."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import HubReadModelsDep
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES
from agent_hub.core.projects.project_views import (
    ProjectDetail,
    ProjectNow,
    ProjectSummary,
    RepoView,
)
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["projects"], responses=PROBLEM_RESPONSES)

ProjectPath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]


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
