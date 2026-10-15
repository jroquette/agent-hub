"""``/workflows``: the workflows of the registered hubs, read from their files on request."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import WorkflowReadsDep
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.workflows.workflow_reads import WorkflowCatalogView, WorkflowDetail

router = APIRouter(tags=["workflows"], responses=PROBLEM_RESPONSES)

NamePath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]


@router.get("/workflows")
def list_workflows(reads: WorkflowReadsDep, *, project: ProjectParam = None) -> WorkflowCatalogView:
    """The workflows of every (or one) project, and the files that do not load."""
    return reads.list_workflows(Scope(project=project))


@router.get("/workflows/{project}/{name}")
def get_workflow(project: NamePath, name: NamePath, reads: WorkflowReadsDep) -> WorkflowDetail:
    """One workflow: its document and its layers."""
    return reads.get_workflow(project, name)
