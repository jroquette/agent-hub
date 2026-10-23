"""``/skill-usage``: the hub's skills and agents with their runs over 7, 30 and 90 days, never
used in the chosen window first (AGH-482). Read-only, one call to the hub read models; names,
counts and times only (ADR 0019)."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BeforeValidator

from agent_hub.api.dependencies import HubReadModelsDep
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.skills.skill_view import UsageDays, UsageReport

router = APIRouter(tags=["skills"], responses=PROBLEM_RESPONSES)


def _number(value: object) -> object:
    """A query string's digits as an int, so ``days=7`` meets the ``Literal[7, 30, 90]``."""
    return int(value) if isinstance(value, str) and value.isdecimal() else value


DaysParam = Annotated[UsageDays, BeforeValidator(_number), Query()]


@router.get("/skill-usage")
def get_skill_usage(
    models: HubReadModelsDep,
    *,
    project: ProjectParam = None,
    days: DaysParam = 30,
) -> UsageReport:
    """The skills and agents of every (or one) project's hub, never used in ``days`` first."""
    return models.skill_usage_report(Scope(project=project), days=days)
