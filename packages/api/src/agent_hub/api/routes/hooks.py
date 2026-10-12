"""``POST /events/hooks``: the hook sensor's envelopes."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.routing import APIRoute

from agent_hub.api.dependencies import IngestHookDep
from agent_hub.api.rfc9457 import problem
from agent_hub.api.schemas import PROBLEM_RESPONSES, HookAccepted
from agent_hub.core.ingestion.hook_envelope import MAX_JSON_DEPTH, HookEnvelope

_QUOTE = ord('"')
_BACKSLASH = ord("\\")
_NESTING = {ord("["): 1, ord("{"): 1, ord("]"): -1, ord("}"): -1}


def json_depth_exceeds(body: bytes, limit: int = MAX_JSON_DEPTH) -> bool:
    """Whether ``body`` nests arrays and objects deeper than ``limit``, read without parsing.

    Brackets inside strings do not count. One linear pass over at most 1 MiB (the security
    middleware cut the body); it keeps the JSON parser's recursion bounded.
    """
    depth = 0
    in_string = escaped = False
    for byte in body:
        if in_string:
            in_string, escaped = _string_state(byte, escaped=escaped)
            continue
        in_string = byte == _QUOTE
        depth += _NESTING.get(byte, 0)
        if depth > limit:
            return True
    return False


def _string_state(byte: int, *, escaped: bool) -> tuple[bool, bool]:
    # (still in the string, next byte escaped) after ``byte`` inside a string.
    if escaped:
        return True, False
    if byte == _BACKSLASH:
        return True, True
    return byte != _QUOTE, False


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
