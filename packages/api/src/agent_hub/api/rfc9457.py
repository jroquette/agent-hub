"""RFC 9457 Problem Details: every error the API answers is one of these documents.

Each named domain exception maps to one problem here, in one table (API.md "Error mapping").
Problems never carry an exception's message unless the table says the message is safe, and an
unexpected exception becomes a generic 500 with no detail: messages and tracebacks can quote
payload text, and payload text can hold a secret (AC-200.21).
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import JsonValue
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_hub.core.agent_sessions.errors import (
    AgentSessionNotFoundError,
    CloudFailedError,
    CloudTimeoutError,
    CloudUnavailableError,
    InvalidDecisionError,
    InvalidWorkdirError,
    LiveLimitError,
    LogFullError,
    MessageTooLargeError,
    PermissionAnsweredError,
    SessionBusyError,
    SessionsOffError,
    SessionsUnavailableError,
    SessionTerminalError,
    UnknownPermissionError,
    UnknownResumeError,
)
from agent_hub.core.brain.brain_note import BrainNoteNotFoundError, BrainNoteTooLargeError
from agent_hub.core.brain.brain_path import BrainPathError
from agent_hub.core.errors import AgentHubError, EventConflictError
from agent_hub.core.learnings.brain_change_requests import (
    ChangeRequestConflictError,
    ChangeRequestError,
    ChangeRequestFailedError,
    ChangeRequestTimeoutError,
    RefspecRefusedError,
)
from agent_hub.core.learnings.learning_ports import HubReadOnlyError, LearningConflictError
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.storage.errors import DatabaseAccessError

PROBLEM_MEDIA_TYPE = "application/problem+json"
LOGGER = logging.getLogger("agent_hub.api")

# Where a request parameter comes from, as RequestValidationError locates it.
PARAMETER_LOCATIONS = ("query", "path", "header", "cookie")


class NotImplementedInBuildError(AgentHubError):
    """A route of the contract whose behaviour this build does not have yet (answers 501)."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"{operation} is not implemented in this build")


class InvalidParameterError(AgentHubError):
    """A request parameter is well formed but not acceptable (answers 400 naming it)."""

    def __init__(self, *, parameter: str, reason: str) -> None:
        self.parameter = parameter
        self.reason = reason
        super().__init__(f"invalid parameter {parameter!r}: {reason}")


class BodyTooLargeError(HTTPException):
    """The request body passed the cap while it was being read.

    An ``HTTPException``, so FastAPI's body reader lets it through instead of answering 400.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(status_code=413)


@dataclass(frozen=True)
class Problem:
    """What a problem document says, before it becomes a response."""

    status: int
    title: str
    detail: str | None = None
    members: Mapping[str, JsonValue] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)


# Each factory takes the exception class it is registered for in the table.
type ProblemFactory = Callable[[Any], Problem]


def problem(
    status: int,
    *,
    title: str,
    detail: str | None = None,
    instance: str | None = None,
    members: Mapping[str, JsonValue] | None = None,
) -> JSONResponse:
    """A Problem Details response; ``detail`` and ``instance`` are left out when None.

    ``members`` are extension members (``errors``), added after the standard ones.
    """
    document: dict[str, object] = {"type": "about:blank", "title": title, "status": status}
    if detail is not None:
        document["detail"] = detail
    if instance is not None:
        document["instance"] = instance
    document.update(members or {})
    return JSONResponse(document, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


def not_found_problem(error: EntityNotFoundError) -> Problem:
    """``EntityNotFoundError``: 404 naming the entity and the id that was asked for."""
    entity = error.entity.capitalize()
    return Problem(404, f"{entity} not found", f"No {error.entity} with id '{error.entity_id}'.")


def busy_problem(_: Exception) -> Problem:
    """The event database is locked by another writer for longer than the busy timeout."""
    return Problem(
        503,
        "Collector database busy",
        "Another process is writing to the event database. Try again in a moment.",
    )


def invalid_cursor_problem(_: Any) -> Problem:
    """``InvalidCursorError`` (core/readmodels/cursor): 400 naming the ``cursor`` parameter."""
    return _invalid_parameter_problem(
        InvalidParameterError(parameter="cursor", reason="not a cursor this server issued")
    )


def hub_invalid_problem(error: Any) -> Problem:
    """``HubInvalidError`` (core/hubs): 422 with its title and one ``errors`` entry per problem.

    Its ``problems`` are pointer/message pairs, as objects or as tuples.
    """
    errors: list[JsonValue] = []
    for item in getattr(error, "problems", ()):
        pointer, message = (
            (item.pointer, item.message) if hasattr(item, "pointer") else (item[0], item[1])
        )
        errors.append({"pointer": str(pointer), "message": str(message)})
    title = str(getattr(error, "title", "Invalid hub.json"))
    return Problem(422, title, str(error), {"errors": errors})


def hub_conflict_problem(error: Any) -> Problem:
    """``HubConflictError`` (core/hubs): 409, the hub or its project is registered already."""
    return Problem(409, "Hub already registered", str(error))


def hub_registry_problem(_: Any) -> Problem:
    """``HubRegistryError`` (core/hubs): 503; the cause names files, so it stays in the log."""
    return Problem(
        503, "Hub registry unreadable", "The registry of hubs could not be read or written."
    )


def _database_problem(_: Exception) -> Problem:
    # The adapter's message names the file and the driver's error; neither helps the browser.
    return Problem(
        503, "Collector database unavailable", "The event database could not be read or written."
    )


def _conflict_problem(error: EventConflictError) -> Problem:
    return Problem(
        409,
        "Event conflict",
        f"An event with key ({error.source}, {error.source_id}) is stored with other content.",
    )


def _invalid_parameter_problem(error: InvalidParameterError) -> Problem:
    return Problem(
        400,
        "Invalid request parameter",
        f"Invalid parameter '{error.parameter}': {error.reason}",
        {"errors": [{"parameter": error.parameter, "message": error.reason}]},
    )


def body_too_large_problem(error: BodyTooLargeError) -> Problem:
    """413: the body is over the cap (by its ``Content-Length`` or while read)."""
    return Problem(
        413, "Request body too large", f"Request bodies are limited to {error.limit} bytes."
    )


def _brain_path_problem(error: BrainPathError) -> Problem:
    # The reasons are the brain rules' own words; none quotes the path.
    return Problem(
        400,
        "Invalid brain path",
        error.reason,
        {"errors": [{"parameter": "path", "message": error.reason}]},
    )


def _brain_note_not_found_problem(_: BrainNoteNotFoundError) -> Problem:
    # One answer for missing, linked, personal and non-regular paths: existence is not revealed.
    return Problem(404, "Brain note not found", "No note at this path in the project's brain.")


def _brain_note_too_large_problem(error: BrainNoteTooLargeError) -> Problem:
    return Problem(
        413,
        "Brain note too large",
        f"Brain notes are served up to {error.limit} bytes; this one has {error.size}.",
    )


def _learning_conflict(*, code: str, reason: str, pr_url: str | None = None) -> Problem:
    members: dict[str, JsonValue] = {"code": code, "reason": reason}
    if pr_url is not None:
        members["pr_url"] = pr_url
    return Problem(409, "Learning cannot be decided", reason, members)


def _learning_conflict_problem(error: LearningConflictError) -> Problem:
    return _learning_conflict(code="learning_conflict", reason=error.reason, pr_url=error.pr_url)


def _change_request_conflict_problem(error: ChangeRequestConflictError) -> Problem:
    return _learning_conflict(code="change_request_conflict", reason=error.reason)


def _push_refused_problem(error: RefspecRefusedError) -> Problem:
    return _learning_conflict(code="push_refused", reason=error.reason)


def _hub_read_only_problem(error: HubReadOnlyError) -> Problem:
    return Problem(
        409,
        "Learning actions unavailable",
        error.reason,
        {"code": "hub_read_only", "reason": error.reason},
    )


_PULL_REQUEST_FAILED = "Could not open the pull request"


def _change_request_failed_problem(error: ChangeRequestFailedError) -> Problem:
    # The step's name only: git and gh output can quote remotes, paths and tokens (ADR 0024).
    return Problem(
        502,
        _PULL_REQUEST_FAILED,
        f"The {error.step} step failed; nothing was merged.",
        {"step": error.step},
    )


def _change_request_error_problem(_: ChangeRequestError) -> Problem:
    return Problem(502, _PULL_REQUEST_FAILED, "A git or gh step failed; nothing was merged.")


def _change_request_timeout_problem(_: ChangeRequestTimeoutError) -> Problem:
    return Problem(
        504,
        "Could not open the pull request in time",
        "The action passed its deadline; nothing was merged.",
    )


def _not_implemented_problem(error: NotImplementedInBuildError) -> Problem:
    return Problem(501, "Not implemented in this build", str(error))


# Agent sessions (RT): each core error is a problem of type ``<prefix><code>``. Details name
# ids, limits and causes only, never conversation text or a value the browser sent (privacy NFR).
AGENT_SESSION_PROBLEM_PREFIX = "urn:agent-hub:problem:agent-session-"
AGENT_SESSIONS_OFF_TYPE = "urn:agent-hub:problem:agent-sessions-off"


def _agent_session_problem(
    status: int,
    code: str,
    title: str,
    *,
    detail: str,
    members: Mapping[str, JsonValue] | None = None,
) -> Problem:
    return Problem(
        status, title, detail, {"type": f"{AGENT_SESSION_PROBLEM_PREFIX}{code}", **(members or {})}
    )


def _agent_session_not_found_problem(error: AgentSessionNotFoundError) -> Problem:
    return _agent_session_problem(
        404,
        "not-found",
        "Agent session not found",
        detail=f"No agent session with id '{error.entity_id}'.",
    )


def _session_terminal_problem(error: SessionTerminalError) -> Problem:
    return _agent_session_problem(
        409,
        "terminal",
        "Agent session ended",
        detail=f"The agent session is {error.status}; resume it to go on.",
        members={"session_status": error.status},
    )


def _session_busy_problem(_: SessionBusyError) -> Problem:
    return _agent_session_problem(
        409,
        "busy",
        "Agent session busy",
        detail="The session is ending its turn after an interrupt; try again after its result.",
    )


def _live_limit_problem(error: LiveLimitError) -> Problem:
    return _agent_session_problem(
        429,
        "limit",
        "Too many live agent sessions",
        detail=f"At most {error.limit} agent sessions can be live; close one to start another.",
        members={"limit": error.limit},
    )


def _log_full_problem(_: LogFullError) -> Problem:
    return _agent_session_problem(
        409,
        "log-full",
        "Agent session log full",
        detail="The agent session's log reached its cap and the session ended; Resume it to go on.",
    )


def _permission_answered_problem(error: PermissionAnsweredError) -> Problem:
    return _agent_session_problem(
        409,
        "answered",
        "Permission request already answered",
        detail="This permission request was already answered; the first answer stands.",
        members={"request_id": error.request_id},
    )


def _unknown_permission_problem(error: UnknownPermissionError) -> Problem:
    return _agent_session_problem(
        404,
        "unknown-request",
        "Permission request not found",
        detail="The agent session has no pending permission request with this id.",
        members={"request_id": error.request_id},
    )


def _invalid_decision_problem(error: InvalidDecisionError) -> Problem:
    # The reason is the policy's own words; it names fields, never the answer's text.
    return _agent_session_problem(
        422,
        "invalid-decision",
        "Invalid permission answer",
        detail=f"Invalid permission answer: {error.reason}.",
    )


def _body_field_problem(code: str, title: str, *, pointer: str, detail: str) -> Problem:
    return _agent_session_problem(
        422,
        code,
        title,
        detail=detail,
        members={"errors": [{"pointer": pointer, "message": detail}]},
    )


def _invalid_workdir_problem(_: InvalidWorkdirError) -> Problem:
    return _body_field_problem(
        "invalid-workdir",
        "Unknown workdir",
        pointer="/workdir_id",
        detail="No workdir with this id in the project; GET /workdirs lists them.",
    )


def _unknown_resume_problem(_: UnknownResumeError) -> Problem:
    return _body_field_problem(
        "unknown-resume",
        "Unknown session to resume",
        pointer="/resume_session_id",
        detail="No resumable session with this id in the workdir; GET /resumable lists them.",
    )


def _message_too_large_problem(error: MessageTooLargeError) -> Problem:
    return _agent_session_problem(
        413,
        "message-too-large",
        "Message too large",
        detail=f"Messages are limited to {error.limit} bytes (UTF-8); this one has {error.size}.",
        members={"limit": error.limit, "size": error.size},
    )


def _sessions_unavailable_problem(error: SessionsUnavailableError) -> Problem:
    return _agent_session_problem(
        503,
        "unavailable",
        "Agent sessions unavailable",
        detail=error.reason,
        members={"reason": error.reason},
    )


def _sessions_off_problem(_: SessionsOffError) -> Problem:
    return Problem(
        404,
        "Agent sessions off",
        "Agent sessions are off in the container.",
        {"type": AGENT_SESSIONS_OFF_TYPE},
    )


def _cloud_unavailable_problem(error: CloudUnavailableError) -> Problem:
    return _agent_session_problem(
        501,
        "cloud-unavailable",
        "Cloud sessions unavailable",
        detail=error.guidance,
        members={"guidance": error.guidance},
    )


def _cloud_failed_problem(error: CloudFailedError) -> Problem:
    # The step's name only: the CLI's output can quote paths, ids and tokens.
    return _agent_session_problem(
        502,
        "cloud-failed",
        "Cloud command failed",
        detail=f"The cloud command failed at the {error.step} step.",
        members={"step": error.step},
    )


def _cloud_timeout_problem(error: CloudTimeoutError) -> Problem:
    return _agent_session_problem(
        504,
        "cloud-timeout",
        "Cloud command timed out",
        detail=f"The cloud command passed its {error.seconds} s deadline and was stopped.",
        members={"seconds": error.seconds},
    )


AGENT_SESSION_PROBLEMS: Mapping[type[Exception], ProblemFactory] = {
    AgentSessionNotFoundError: _agent_session_not_found_problem,
    SessionTerminalError: _session_terminal_problem,
    SessionBusyError: _session_busy_problem,
    LiveLimitError: _live_limit_problem,
    LogFullError: _log_full_problem,
    PermissionAnsweredError: _permission_answered_problem,
    UnknownPermissionError: _unknown_permission_problem,
    InvalidDecisionError: _invalid_decision_problem,
    InvalidWorkdirError: _invalid_workdir_problem,
    UnknownResumeError: _unknown_resume_problem,
    MessageTooLargeError: _message_too_large_problem,
    SessionsUnavailableError: _sessions_unavailable_problem,
    SessionsOffError: _sessions_off_problem,
    CloudUnavailableError: _cloud_unavailable_problem,
    CloudFailedError: _cloud_failed_problem,
    CloudTimeoutError: _cloud_timeout_problem,
}


# The one place where a named exception becomes a problem. Starlette picks the closest class in
# the exception's MRO, so a subclass entry (a busy database) wins over its base.
PROBLEMS: Mapping[type[Exception], ProblemFactory] = {
    EntityNotFoundError: not_found_problem,
    EventConflictError: _conflict_problem,
    DatabaseAccessError: _database_problem,
    InvalidParameterError: _invalid_parameter_problem,
    BodyTooLargeError: body_too_large_problem,
    NotImplementedInBuildError: _not_implemented_problem,
    BrainPathError: _brain_path_problem,
    BrainNoteNotFoundError: _brain_note_not_found_problem,
    BrainNoteTooLargeError: _brain_note_too_large_problem,
    LearningConflictError: _learning_conflict_problem,
    HubReadOnlyError: _hub_read_only_problem,
    ChangeRequestError: _change_request_error_problem,
    ChangeRequestConflictError: _change_request_conflict_problem,
    RefspecRefusedError: _push_refused_problem,
    ChangeRequestFailedError: _change_request_failed_problem,
    ChangeRequestTimeoutError: _change_request_timeout_problem,
    **AGENT_SESSION_PROBLEMS,
}


def _validation_problem(error: RequestValidationError) -> Problem:
    """400 for a bad query, path or header parameter, 422 for a bad body; both name the field.

    The offending value is never echoed: it can be anything the client sent.
    """
    parameters: list[dict[str, JsonValue]] = []
    pointers: list[dict[str, JsonValue]] = []
    for item in error.errors():
        location, *path = (str(part) for part in item.get("loc", ("body",)))
        message = str(item.get("msg", "invalid"))
        if location in PARAMETER_LOCATIONS:
            name = path[0] if path else location
            parameters.append({"location": location, "parameter": name, "message": message})
        else:
            pointer = "/" + "/".join(path)
            pointers.append({"location": location, "pointer": pointer, "message": message})
    if pointers or not parameters:
        first = pointers[0] if pointers else {"pointer": "/", "message": "invalid"}
        detail = f"Invalid request body at '{first['pointer']}': {first['message']}"
        errors: list[JsonValue] = [*pointers, *parameters]
        return Problem(422, "Invalid request body", detail, {"errors": errors})
    first = parameters[0]
    detail = f"Invalid {first['location']} parameter '{first['parameter']}': {first['message']}"
    return Problem(
        400, "Invalid request parameter", detail, {"errors": list[JsonValue](parameters)}
    )


def _http_problem(error: HTTPException) -> Problem:
    # Starlette's own errors (no route, wrong method): the reason phrase, no detail.
    return Problem(
        error.status_code, HTTPStatus(error.status_code).phrase, headers=error.headers or {}
    )


def _respond(request: Request, found: Problem) -> Response:
    response = problem(
        found.status,
        title=found.title,
        detail=found.detail,
        instance=request.url.path,
        members=found.members,
    )
    response.headers.update(found.headers)
    return response


def _handler(factory: ProblemFactory) -> Callable[[Request, Exception], Response]:
    def handle(request: Request, error: Exception) -> Response:
        return _respond(request, factory(error))

    return handle


def install_problem_handlers(
    app: FastAPI, *, extra: Mapping[type[Exception], ProblemFactory] | None = None
) -> None:
    """Answer the table's exceptions, validation errors and HTTP errors with problems.

    ``extra`` adds entries for errors this module cannot import (the composition passes them).
    """
    for error_type, factory in {**PROBLEMS, **(extra or {})}.items():
        app.add_exception_handler(error_type, _handler(factory))
    app.add_exception_handler(RequestValidationError, _handler(_validation_problem))
    app.add_exception_handler(HTTPException, _handler(_http_problem))


class UnhandledErrorMiddleware:
    """Turns any exception that escapes the routes into a generic 500 problem.

    Starlette's own error middleware answers too but then re-raises, so the server would log
    the traceback, and with it any secret the exception quotes. This one logs only the
    exception's class and the route, and answers ``{"title": "Internal server error"}``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as error:  # noqa: BLE001 -- the last line of defence answers 500
            # The class name only: a message or traceback could quote a secret.
            LOGGER.error("unhandled error", extra={"error_type": type(error).__name__})
            if not started:
                response = problem(500, title="Internal server error", instance=scope["path"])
                await response(scope, receive, send)
