"""``GET /collector/status``: what the running server received and stored."""

from fastapi import APIRouter

from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import PROBLEM_RESPONSES
from agent_hub.core.ingestion.ingestion_status import CollectorStatus

router = APIRouter(tags=["collector"], responses=PROBLEM_RESPONSES)


@router.get("/collector/status")
def get_collector_status() -> CollectorStatus:
    """The collector's counters and sources."""
    raise NotImplementedInBuildError("get_collector_status")
