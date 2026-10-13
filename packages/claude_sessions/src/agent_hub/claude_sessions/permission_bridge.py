"""The SDK's ``can_use_tool`` callback, parked until the browser answers (D.4).

Each call becomes a ``PermissionRequest`` event and waits on a future, with no deadline of its
own: ``hub web``'s permission timeout (``AgentSessionControl.sweep``) answers it ``deny`` when
it passes. The request id is the tool use id when it is a safe id (so the browser can tie the
request to its tool card), else a minted one. ``AskUserQuestion`` and ``ExitPlanMode`` requests
are marked as such. Suggestions are the CLI's own rules, passed back verbatim on "always".

``deny_all`` answers every parked request (interrupt, close); after ``close`` new requests are
denied at once. When the CLI cancels a request, it is forgotten.
"""

import asyncio
import re
from collections.abc import Callable
from typing import Any, Final, cast

from claude_agent_sdk import (
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ToolPermissionContext,
)
from pydantic import JsonValue

from agent_hub.core.agent_sessions.driver import (
    Allow,
    Deny,
    DriverAnswer,
    DriverEvent,
    PermissionRequest,
    PermissionSuggestion,
    RequestKind,
)
from agent_hub.core.agent_sessions.errors import PermissionAnsweredError, UnknownPermissionError

CLOSED: Final = "session closed"
INTERRUPTED: Final = "interrupted"
NO_DESTINATION: Final = "unspecified"
REQUEST_KINDS: Final[dict[str, RequestKind]] = {
    "AskUserQuestion": "ask_user_question",
    "ExitPlanMode": "plan_approval",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _suggestion(index: int, update: PermissionUpdate) -> PermissionSuggestion:
    rule = cast("JsonValue", update.to_dict())
    return PermissionSuggestion(
        index=index, destination=update.destination or NO_DESTINATION, rule=rule
    )


def _sdk_result(answer: DriverAnswer) -> PermissionResult:
    if not isinstance(answer, Allow):
        return PermissionResultDeny(message=answer.message)
    updates = [
        PermissionUpdate.from_dict(dict(suggestion.rule))
        for suggestion in answer.updated_permissions
        if isinstance(suggestion.rule, dict)
    ]
    return PermissionResultAllow(
        updated_input=None if answer.updated_input is None else dict(answer.updated_input),
        updated_permissions=updates or None,
    )


class PermissionBridge:
    """Parks permission requests of one session; ``emit`` hands each to its event stream."""

    def __init__(self, emit: Callable[[DriverEvent], None]) -> None:
        self._emit = emit
        self._pending: dict[str, asyncio.Future[DriverAnswer]] = {}
        self._answered: set[str] = set()
        self._minted = 0
        self._closed = False

    async def can_use_tool(
        self, tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResult:
        """The SDK callback: emit the request, wait for its answer."""
        if self._closed:
            return PermissionResultDeny(message=CLOSED)
        request_id = self._request_id(context.tool_use_id)
        future: asyncio.Future[DriverAnswer] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            self._emit(
                PermissionRequest(
                    request_id=request_id,
                    tool=tool_name,
                    input=cast("dict[str, JsonValue]", tool_input),
                    suggestions=tuple(
                        _suggestion(index, update)
                        for index, update in enumerate(context.suggestions)
                    ),
                    request_kind=REQUEST_KINDS.get(tool_name, "tool"),
                )
            )
            answer = await future
        finally:
            self._pending.pop(request_id, None)
        return _sdk_result(answer)

    def answer(self, request_id: str, answer: DriverAnswer) -> None:
        """Resolve a parked request; unknown or already answered ones raise."""
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            if request_id in self._answered:
                raise PermissionAnsweredError(request_id)
            raise UnknownPermissionError(request_id)
        self._answered.add(request_id)
        future.set_result(answer)

    def pending(self) -> tuple[str, ...]:
        """The ids of the requests still parked, oldest first."""
        return tuple(self._pending)

    def deny_all(self, message: str) -> None:
        """Answer every parked request ``deny`` with ``message``."""
        for request_id, future in list(self._pending.items()):
            if not future.done():
                future.set_result(Deny(message=message))
            self._answered.add(request_id)
        self._pending.clear()

    def close(self) -> None:
        """Deny what is parked and every later request."""
        self._closed = True
        self.deny_all(CLOSED)

    def _request_id(self, tool_use_id: str | None) -> str:
        taken = tool_use_id is None or tool_use_id in self._pending or tool_use_id in self._answered
        if not taken and tool_use_id is not None and _SAFE_ID.fullmatch(tool_use_id):
            return tool_use_id
        self._minted += 1
        return f"permission-{self._minted}"
