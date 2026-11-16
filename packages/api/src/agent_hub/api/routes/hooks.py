"""``POST /events/hooks``: the hook sensor's envelopes."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.routing import APIRoute

from agent_hub.api.dependencies import IngestHookDep
from agent_hub.api.rfc9457 import problem
from agent_hub.api.schemas import PROBLEM_RESPONSES, HookAccepted
from agent_hub.core.ingestion.hook_envelope import (
    MAX_JSON_DEPTH,
    HookEnvelope,
    json_depth_exceeds,
)


class DepthCheckedRoute(APIRoute):
    """A route that refuses a body nested deeper than ``MAX_JSON_DEPTH`` before parsing it."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """The default handler, behind the depth check."""
        handler = super().get_route_handler()

        async def checked(request: Request) -> Response:
            if json_depth_exceeds(await request.body()):
                return problem(
                    422,
                    title="Invalid request body",
                    detail=f"The body nests deeper than {MAX_JSON_DEPTH} levels.",
                    instance=request.url.path,
                )
            return await handler(request)

        return checked


router = APIRouter(tags=["ingestion"], responses=PROBLEM_RESPONSES, route_class=DepthCheckedRoute)


@router.post("/events/hooks", status_code=202)
def post_hook(envelope: HookEnvelope, ingest: IngestHookDep) -> HookAccepted:
    """Map one hook envelope to events and append them (redacted)."""
    result = ingest.execute(envelope)
    return HookAccepted(appended=result.appended, duplicates=result.duplicates)
