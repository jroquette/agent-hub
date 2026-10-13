"""The permission policy (D5, E7): which answers fit a request, and when a request expires.

Pure. ``PermissionDecision`` already refuses the combinations that never fit (``always``
without a suggestion, a message outside ``deny``...); ``validate`` checks the rest against the
request itself and builds what the driver receives:

- ``allow``: allow once; ``answers`` only for an ``AskUserQuestion`` (they go into the
  updated input, beside its questions), ``mode`` only for a plan approval (the use case
  changes the mode after the allow, E6).
- ``deny``: deny with the owner's message.
- ``always``: allow with exactly the suggestion at that index, passed through verbatim, and
  only when its destination is ``localSettings``.

A request nobody answers is denied at its deadline (``by: timeout``); closing or interrupting
the session denies it too (``by: closed``).
"""

from datetime import datetime
from typing import Final

from pydantic import JsonValue

from agent_hub.core.agent_sessions.agent_session import OpenPermission, PermissionDecision
from agent_hub.core.agent_sessions.driver import (
    Allow,
    Deny,
    DriverAnswer,
    PermissionRequest,
    PermissionSuggestion,
)
from agent_hub.core.agent_sessions.errors import InvalidDecisionError
from agent_hub.core.agent_sessions.limits import SessionLimits

# The only destination "Always allow" may write to (D5).
ALWAYS_DESTINATION: Final = "localSettings"
TIMEOUT_MESSAGE: Final = "No answer came from hub web before the permission timeout."
CLOSED_MESSAGE: Final = "The hub web session was closed or interrupted."


def validate(request: PermissionRequest, decision: PermissionDecision) -> DriverAnswer:
    """What the driver receives for ``decision``; ``InvalidDecisionError`` when it does not fit
    ``request``."""
    if decision.answers is not None and request.request_kind != "ask_user_question":
        msg = "answers fit only an AskUserQuestion request"
        raise InvalidDecisionError(msg)
    if decision.mode is not None and request.request_kind != "plan_approval":
        msg = "a mode fits only a plan approval"
        raise InvalidDecisionError(msg)
    match decision.decision:
        case "deny":
            return Deny(message=decision.message or "")
        case "always":
            return Allow(updated_permissions=(_suggestion(request, decision.suggestion),))
        case "allow":
            if decision.answers is None:
                return Allow()
            answers: dict[str, JsonValue] = dict(decision.answers)
            return Allow(updated_input=request.input | {"answers": answers})


def _suggestion(request: PermissionRequest, index: int | None) -> PermissionSuggestion:
    for suggestion in request.suggestions:
        if suggestion.index == index:
            if suggestion.destination != ALWAYS_DESTINATION:
                msg = f"suggestion {index} is not a {ALWAYS_DESTINATION} rule"
                raise InvalidDecisionError(msg)
            return suggestion
    msg = f"no suggestion {index} in this request"
    raise InvalidDecisionError(msg)


def deadline(asked_at: datetime, limits: SessionLimits) -> datetime:
    """When a request asked at ``asked_at`` is denied if nobody answers."""
    return asked_at + limits.permission_timeout


def expired(open_request: OpenPermission, now: datetime) -> bool:
    """Whether ``open_request`` has reached its deadline at ``now``."""
    return now >= open_request.deadline_at


def timeout_answer() -> Deny:
    """The answer the driver receives when a request's deadline passes."""
    return Deny(message=TIMEOUT_MESSAGE)


def closed_answer() -> Deny:
    """The answer the driver receives for a request pending when the session closes or is
    interrupted."""
    return Deny(message=CLOSED_MESSAGE)
