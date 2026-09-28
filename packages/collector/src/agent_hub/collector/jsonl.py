"""Canonical events from JSON Lines text: one event per line, every bad line reported."""

import json
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_hub.collector.errors import InputNotFoundError, InputUnreadableError
from agent_hub.core.events.event import Event

NESTED_TOO_DEEPLY = "invalid JSON: nested too deeply"
# A reason is printed after "line <n>: ", so a whole stderr line stays within 300 characters.
MAX_REASON_LENGTH = 280
# Location parts shown before the rest is elided; pydantic lists every level of a deep value.
MAX_LOCATION_PARTS = 5


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
    """The UTF-8 text of ``path``, a leading BOM dropped (RFC 8259 lets parsers ignore it).

    I/O and decoding errors become collector errors.
    """
    # The path comes from the user: quoted and escaped, so a message stays on one line.
    quoted = json.dumps(str(path))
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as error:
        msg = f"input file not found: {quoted}"
        raise InputNotFoundError(msg) from error
    except UnicodeDecodeError as error:
        msg = f"cannot read {quoted}: not valid UTF-8 (byte {error.start})"
        raise InputUnreadableError(msg) from error
    except OSError as error:
        msg = f"cannot read {quoted}: {error.strerror or error}"
        raise InputUnreadableError(msg) from error


def read_stream(stream: BinaryIO, *, name: str) -> str:
    """``stream`` as UTF-8 whatever the locale, a leading BOM dropped; ``name`` is for errors."""
    try:
        data = stream.read()
    except (OSError, ValueError) as error:
        # A closed stream raises ValueError.
        msg = f"cannot read {name}: {error}"
        raise InputUnreadableError(msg) from error
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        msg = f"cannot read {name}: not valid UTF-8 (byte {error.start})"
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
            errors.append(LineError(line_number=line_number, reason=_bounded(str(error))))
    return ParsedBatch(events=tuple(events), errors=tuple(errors))


def _parse_line(line: str) -> Event:
    try:
        value = json.loads(
            line, parse_constant=_reject_constant, object_pairs_hook=_reject_duplicate_keys
        )
    except ValueError as error:
        # JSONDecodeError is a ValueError; so are the rejected-constant and duplicate-key errors.
        reason = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
        raise _LineRejectedError(f"invalid JSON: {reason}") from error
    except RecursionError as error:
        raise _LineRejectedError(NESTED_TOO_DEEPLY) from error
    if not isinstance(value, dict):
        msg = "expected a JSON object"
        raise _LineRejectedError(msg)
    try:
        return Event.model_validate(value)
    except ValidationError as error:
        raise _LineRejectedError(_describe_validation_error(error)) from error
    except RecursionError as error:
        raise _LineRejectedError(NESTED_TOO_DEEPLY) from error


def _reject_constant(name: str) -> object:
    # NaN and Infinity are not JSON (RFC 8259); Python's json accepts them by default.
    msg = f"{name} is not allowed"
    raise ValueError(msg)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # Python's json keeps the last of repeated keys, so a second source_id would silently win.
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            msg = f"duplicate key {json.dumps(key)}"
            raise ValueError(msg)
        result[key] = value
    return result


def _describe_validation_error(error: ValidationError) -> str:
    return "; ".join(
        f"{_describe_location(detail['loc'])}: {detail['msg']}" for detail in error.errors()
    )


def _describe_location(location: tuple[int | str, ...]) -> str:
    shown = ".".join(_describe_location_part(part) for part in location[:MAX_LOCATION_PARTS])
    elided = "…" if len(location) > MAX_LOCATION_PARTS else ""
    return f"{shown or 'event'}{elided}"


def _describe_location_part(part: int | str) -> str:
    # Key names come from the input: anything but a plain name is quoted and escaped, so a key
    # cannot break the message across lines or send control characters to the terminal.
    if isinstance(part, int) or part.isidentifier():
        return str(part)
    return json.dumps(part)


def _bounded(reason: str) -> str:
    if len(reason) <= MAX_REASON_LENGTH:
        return reason
    return f"{reason[: MAX_REASON_LENGTH - 1]}…"
