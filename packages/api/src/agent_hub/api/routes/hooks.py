"""``POST /events/hooks``: the hook sensor's envelopes."""

from fastapi import APIRouter

from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import PROBLEM_RESPONSES, HookAccepted
from agent_hub.core.ingestion.hook_envelope import HookEnvelope

router = APIRouter(tags=["ingestion"], responses=PROBLEM_RESPONSES)


@router.post("/events/hooks", status_code=202)
def post_hook(envelope: HookEnvelope) -> HookAccepted:
    """Map one hook envelope to events and append them (redacted)."""
    raise NotImplementedInBuildError("post_hook")
