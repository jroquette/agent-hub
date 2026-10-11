"""``/projects``: Portfolio cards and the Project overview."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.rfc9457 import NotImplementedInBuildError
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
def list_projects() -> Page[ProjectSummary]:
    """A card per registered project."""
    raise NotImplementedInBuildError("list_projects")


@router.get("/projects/{project}")
def get_project(project: ProjectPath) -> ProjectDetail:
    """The Project overview header."""
    raise NotImplementedInBuildError("get_project")


@router.get("/projects/{project}/now")
def get_project_now(project: ProjectPath) -> ProjectNow:
    """The project's ``brain/now.md``."""
    raise NotImplementedInBuildError("get_project_now")


@router.get("/projects/{project}/repos")
def list_project_repos(project: ProjectPath) -> Page[RepoView]:
    """The project's repos."""
    raise NotImplementedInBuildError("list_project_repos")
