"""``/workflow-runs``: the Workflow runs list and Run detail."""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from agent_hub.api.dependencies import EventReadModelsDep, parse_filter
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

router = APIRouter(tags=["runs"], responses=PROBLEM_RESPONSES)

TextParam = Annotated[str | None, Query(min_length=1, max_length=MAX_QUERY_TEXT)]


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
