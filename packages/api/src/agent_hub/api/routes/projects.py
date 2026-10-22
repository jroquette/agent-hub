"""``/projects``: Portfolio cards and the Project overview."""

from typing import Annotated

from fastapi import APIRouter, Body, Path, Query
from pydantic import TypeAdapter, ValidationError

from agent_hub.api.dependencies import HubReadModelsDep
from agent_hub.api.environment_writes import EnvironmentEdit, write_environment_edit
from agent_hub.api.local_settings import LocalSettings, write_local_settings
from agent_hub.api.rfc9457 import InvalidParameterError
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES
from agent_hub.core.brain.brain_note import BrainNote, BrainTree
from agent_hub.core.brain.brain_path import MAX_PATH_CHARS
from agent_hub.core.hub_config.config_view import HubConfigView
from agent_hub.core.hub_config.env_file_keys import EnvFileKeys
from agent_hub.core.hub_config.environments import EnvFilePath
from agent_hub.core.projects.project_views import (
    ProjectDetail,
    ProjectNow,
    ProjectSummary,
    RepoView,
)
from agent_hub.core.readmodels.page import Page
from agent_hub.generator.env_file_reader import env_file_keys

router = APIRouter(tags=["projects"], responses=PROBLEM_RESPONSES)

ProjectPath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]
NotePathParam = Annotated[str, Query(min_length=1, max_length=MAX_PATH_CHARS)]
EnvFileParam = Annotated[str, Query(min_length=1, max_length=MAX_QUERY_TEXT)]
_ENV_FILE_PATH: TypeAdapter[str] = TypeAdapter(EnvFilePath)


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


@router.get("/projects/{project}/config")
def get_project_config(project: ProjectPath, models: HubReadModelsDep) -> HubConfigView:
    """The project's hub config: team (``hub.json``) and local (``hub.local.json``) values."""
    return models.hub_config(project)


@router.put("/projects/{project}/config/local")
def put_project_local_config(
    project: ProjectPath, settings: LocalSettings, models: HubReadModelsDep
) -> HubConfigView:
    """Save this developer's ``hub.local.json`` values; the team's ``hub.json`` is untouched."""
    write_local_settings(models.hub_config(project).hub_path, settings)
    return models.hub_config(project)


@router.post("/projects/{project}/config/environments")
def post_project_environment_edit(
    project: ProjectPath,
    edit: Annotated[EnvironmentEdit, Body()],
    models: HubReadModelsDep,
) -> HubConfigView:
    """Add, change or remove an environment or a service endpoint, in ``hub.json`` (the team's,
    left uncommitted) or ``hub.local.json`` (this developer's), as ``hub env`` does."""
    write_environment_edit(models.hub_config(project).hub_path, edit)
    return models.hub_config(project)


@router.get("/projects/{project}/env-file-keys")
def get_env_file_keys(
    project: ProjectPath, path: EnvFileParam, models: HubReadModelsDep
) -> EnvFileKeys:
    """The variable NAMES an env file holds, never a value: only a regular file of at most
    64 KiB inside the hub or one of its repos, with whether git ignores it there."""
    try:
        checked = _ENV_FILE_PATH.validate_python(path)
    except ValidationError as error:
        raise InvalidParameterError(
            parameter="path",
            reason="relative to the workspace, no .., no leading / or ~, no space",
        ) from error
    view = models.hub_config(project)
    return env_file_keys(view.hub_path, [repo.dir for repo in view.repos], checked)


@router.get("/projects/{project}/brain")
def get_brain_tree(project: ProjectPath, models: HubReadModelsDep) -> BrainTree:
    """The ``.md`` notes of the project's hub brain (``auto/`` excluded)."""
    return models.brain_tree(project)


@router.get("/projects/{project}/brain/note")
def get_brain_note(
    project: ProjectPath, path: NotePathParam, models: HubReadModelsDep
) -> BrainNote:
    """One brain note by its path under ``brain/``: frontmatter, markdown body and size."""
    return models.brain_note(project, path)
