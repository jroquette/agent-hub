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

from agent_hub.core.errors import AgentHubError, EventConflictError
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


def _not_implemented_problem(error: NotImplementedInBuildError) -> Problem:
    return Problem(501, "Not implemented in this build", str(error))


# The one place where a named exception becomes a problem. Starlette picks the closest class in
# the exception's MRO, so a subclass entry (a busy database) wins over its base.
PROBLEMS: Mapping[type[Exception], ProblemFactory] = {
    EntityNotFoundError: not_found_problem,
    EventConflictError: _conflict_problem,
    DatabaseAccessError: _database_problem,
    InvalidParameterError: _invalid_parameter_problem,
    BodyTooLargeError: body_too_large_problem,
    NotImplementedInBuildError: _not_implemented_problem,
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
