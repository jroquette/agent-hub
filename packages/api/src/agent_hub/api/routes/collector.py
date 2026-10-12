"""``GET /collector/status``: what the running server received and stored."""

from fastapi import APIRouter

from agent_hub.api.dependencies import CollectorPortsDep, SettingsDep
from agent_hub.api.schemas import PROBLEM_RESPONSES
from agent_hub.core.ingestion.ingestion_status import CollectorStatus

router = APIRouter(tags=["collector"], responses=PROBLEM_RESPONSES)


@router.get("/collector/status")
def get_collector_status(ports: CollectorPortsDep, settings: SettingsDep) -> CollectorStatus:
    """The collector's counters and sources."""
    # The store never deletes, so its high-water mark is the number of events it holds.
    return ports.counters.snapshot(
        db_path=str(settings.db_path),
        running_version=settings.running_version,
        events_total=ports.reader.high_water_mark(),
    )
