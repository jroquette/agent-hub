"""``/workflow-runs``: the Workflow runs list and Run detail, and the run commands (AC-213.19).

Start, cancel, resume and abandon are strict writes that need the launch's cookie (checked
before routing); each is one call to core's ``StartWorkflowRun`` or ``ControlWorkflowRun``.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Response

from agent_hub.api.dependencies import EventReadModelsDep, RunControlDep, RunStartsDep, parse_filter
from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.schemas import (
    DEFAULT_LIMIT,
    MAX_QUERY_TEXT,
    PROBLEM_RESPONSES,
    CursorParam,
    LimitParam,
    ProjectParam,
)
from agent_hub.core.readmodels.filters import RunFilter
from agent_hub.core.readmodels.page import Page
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.runs.workflow_run import WorkflowRun
from agent_hub.core.workflows.failures import FailureKind
from agent_hub.core.workflows.launch import RUN_ID_TEXT, RunAccepted, StartRunRequest

router = APIRouter(tags=["runs"], responses=PROBLEM_RESPONSES)

TextParam = Annotated[str | None, Query(min_length=1, max_length=MAX_QUERY_TEXT)]
RunIdPath = Annotated[str, Path(pattern=RUN_ID_TEXT)]


@router.get("/workflow-runs")
def list_runs(  # noqa: PLR0913 -- one keyword per documented filter of the endpoint
    models: EventReadModelsDep,
    *,
    project: ProjectParam = None,
    repo: TextParam = None,
    stage: Stage | None = None,
    outcome: Literal["done", "failed"] | None = None,
    failure_stage: Stage | None = None,
    mode: Literal["live", "dry_run"] | None = None,
    issue: TextParam = None,
    workflow: TextParam = None,
    failure_kind: FailureKind | None = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> Page[WorkflowRun]:
    """Workflow runs matching the filters, newest first."""
    run_filter = parse_filter(
        RunFilter,
        project=project,
        repo=repo,
        stage=stage,
        outcome=outcome,
        failure_stage=failure_stage,
        mode=mode,
        issue=issue,
        workflow=workflow,
        failure_kind=failure_kind,
        cursor=cursor,
        limit=limit,
    )
    return models.list_runs(run_filter)


@router.get("/workflow-runs/{run_id}")
def get_run(
    run_id: Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)],
    models: EventReadModelsDep,
) -> WorkflowRun:
    """One workflow run with its steps."""
    return models.get_run(run_id)


@router.post("/workflow-runs", status_code=202)
def start_run(body: StartRunRequest, starts: RunStartsDep, response: Response) -> RunAccepted:
    """Start a project's workflow as a ``hub workflow run`` child; its events tell its status."""
    accepted = starts(body)
    response.headers["Location"] = f"{API_PREFIX}/workflow-runs/{accepted.run_id}"
    return accepted


@router.post("/workflow-runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: RunIdPath, control: RunControlDep) -> RunAccepted:
    """Stop the run's child (SIGINT, then SIGKILL), then end the run cancelled."""
    return control.cancel(run_id)


@router.post("/workflow-runs/{run_id}/resume", status_code=202)
def resume_run(run_id: RunIdPath, control: RunControlDep) -> RunAccepted:
    """Continue a failed or unended run in a new child, reusing what completed."""
    return control.resume(run_id)


@router.post("/workflow-runs/{run_id}/abandon")
def abandon_run(run_id: RunIdPath, control: RunControlDep) -> RunAccepted:
    """End a failed or unended run cancelled."""
    return control.abandon(run_id)
