"""Canonical events from JSON Lines text: one event per line, every bad line reported."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_hub.collector.errors import InputNotFoundError, InputUnreadableError
from agent_hub.core.events.event import Event


class ParsedEvent(BaseModel):
    """A valid event and the 1-based line it came from."""

    model_config = ConfigDict(frozen=True)

    line_number: int
    event: Event


class LineError(BaseModel):
    """Why the line at ``line_number`` (1-based) is not a canonical event."""

    model_config = ConfigDict(frozen=True)

    line_number: int
    reason: str


class ParsedBatch(BaseModel):
    """The valid events in input order and one error per bad line."""

    model_config = ConfigDict(frozen=True)

    events: tuple[ParsedEvent, ...]
    errors: tuple[LineError, ...]


class _LineRejectedError(Exception):
    """A line that is not a canonical event; the message is the reason."""


def read_text(path: Path) -> str:
    """The UTF-8 text of the file at ``path``; I/O and decoding errors become collector errors."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        msg = f"input file not found: {path}"
        raise InputNotFoundError(msg) from error
    except UnicodeDecodeError as error:
        msg = f"cannot read {path}: not valid UTF-8 (byte {error.start})"
        raise InputUnreadableError(msg) from error
    except OSError as error:
        msg = f"cannot read {path}: {error.strerror or error}"
        raise InputUnreadableError(msg) from error


def parse_events(text: str) -> ParsedBatch:
    """Parse every line of ``text``; bad lines become ``LineError``s instead of raising.

    Blank and whitespace-only lines are skipped but still count for line numbers. Only
    ``"\\n"`` ends a record (``str.splitlines`` would also split on U+2028 and U+0085,
    which JSON strings may hold unescaped); a trailing ``"\\r"`` is whitespace to JSON.
    """
    events: list[ParsedEvent] = []
    errors: list[LineError] = []
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            events.append(ParsedEvent(line_number=line_number, event=_parse_line(line)))
        except _LineRejectedError as error:
            errors.append(LineError(line_number=line_number, reason=str(error)))
    return ParsedBatch(events=tuple(events), errors=tuple(errors))


def _parse_line(line: str) -> Event:
    try:
        value = json.loads(line, parse_constant=_reject_constant)
    except ValueError as error:
        # JSONDecodeError is a ValueError, and so is the rejected-constant error.
        reason = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
        raise _LineRejectedError(f"invalid JSON: {reason}") from error
    if not isinstance(value, dict):
        msg = "expected a JSON object"
        raise _LineRejectedError(msg)
    try:
        return Event.model_validate(value)
    except ValidationError as error:
        raise _LineRejectedError(_describe_validation_error(error)) from error


def _reject_constant(name: str) -> object:
    # NaN and Infinity are not JSON (RFC 8259); Python's json accepts them by default.
    msg = f"{name} is not allowed"
    raise ValueError(msg)


def _describe_validation_error(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in detail['loc']) or 'event'}: {detail['msg']}"
        for detail in error.errors()
    )
