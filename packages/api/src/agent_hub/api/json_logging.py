"""Structured JSON logs: one line per request, and the formatter every API record uses.

A request line says ``method``, the route's path template (``/api/v1/sessions/{session_id}``,
never the filled-in path), ``status``, ``ms`` and, when the route has them, ``session_id`` and
``project``. Bodies and query strings are never logged: they can hold payload text.
"""

import json
import logging
import sys
import time
from typing import IO

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_hub.api.openapi_paths import API_PREFIX

LOGGER_NAME = "agent_hub.api"
LOGGER = logging.getLogger(LOGGER_NAME)
# The only record attributes the formatter writes besides time, level and message.
LOGGED_FIELDS = ("method", "path", "status", "ms", "session_id", "project", "error_type")
UNMATCHED_PATH = "<unmatched>"


class JsonFormatter(logging.Formatter):
    """One JSON object per record, with the allowed fields only; never an exception's text."""

    def format(self, record: logging.LogRecord) -> str:
        """The record as one line of JSON."""
        document: dict[str, object] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        for name in LOGGED_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                document[name] = value
        return json.dumps(document, separators=(",", ":"))


def configure_logging(stream: IO[str] | None = None) -> None:
    """Send the API's records to ``stream`` (stderr) as JSON lines, once."""
    if any(isinstance(handler.formatter, JsonFormatter) for handler in LOGGER.handlers):
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def request_fields(scope: Scope, *, status: int, ms: float) -> dict[str, object]:
    """What the request line records about one request."""
    route = scope.get("route")
    template = getattr(route, "path_format", None)
    # Routes of an included router keep their path without the router's prefix.
    if template is not None and not template.startswith(API_PREFIX):
        template = f"{API_PREFIX}{template}"
    path_params: dict[str, object] = scope.get("path_params") or {}
    fields: dict[str, object] = {
        "method": scope["method"],
        "path": template or UNMATCHED_PATH,
        "status": status,
        "ms": round(ms, 1),
    }
    for name in ("session_id", "project"):
        if isinstance(path_params.get(name), str):
            fields[name] = path_params[name]
    return fields


class RequestLogMiddleware:
    """Logs one JSON line per HTTP request once it is answered (status 500 when none started)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started_at = time.perf_counter()
        status = 500

        async def recording_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, recording_send)
        finally:
            ms = (time.perf_counter() - started_at) * 1000
            LOGGER.info("request", extra=request_fields(scope, status=status, ms=ms))
