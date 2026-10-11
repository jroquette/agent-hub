"""Opaque snapshot cursors: ``{hwm, key, id}`` as base64url JSON, 512 characters at most.

A list read folds the events up to a high-water mark and pages through the sorted result; the
cursor carries that mark, the sort key of the last item returned and its id, so the next page
folds the same events (later appends wait for a fresh first page) and starts right after that
item: no item repeats and none is skipped (AC-200.32).
"""

import base64
import binascii
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from agent_hub.core.errors import AgentHubError
from agent_hub.core.readmodels.page import MAX_CURSOR_CHARS

type CursorKeyPart = StrictInt | StrictStr | None


class InvalidCursorError(AgentHubError):
    """A cursor that this server did not write, or that was damaged (the API answers 400)."""


class Cursor(BaseModel):
    """Where the next page starts: the snapshot's high-water mark and the last item's key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hwm: Annotated[int, Field(ge=0)]
    key: tuple[CursorKeyPart, ...]
    id: str


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    h: Annotated[StrictInt, Field(ge=0)]
    k: tuple[CursorKeyPart, ...]
    i: StrictStr


def encode_cursor(cursor: Cursor) -> str:
    """``cursor`` as opaque text; ``ValueError`` when it would exceed 512 characters."""
    wire = _Wire(h=cursor.hwm, k=cursor.key, i=cursor.id)
    raw = json.dumps(wire.model_dump(), separators=(",", ":")).encode()
    text = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if len(text) > MAX_CURSOR_CHARS:
        msg = f"cursor would be {len(text)} characters, more than {MAX_CURSOR_CHARS}"
        raise ValueError(msg)
    return text


def decode_cursor(text: str) -> Cursor:
    """The cursor ``encode_cursor`` wrote as ``text``; ``InvalidCursorError`` for anything else."""
    if not text or len(text) > MAX_CURSOR_CHARS:
        msg = f"invalid cursor: expected 1 to {MAX_CURSOR_CHARS} characters"
        raise InvalidCursorError(msg)
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        wire = _Wire.model_validate_json(raw)
    except (binascii.Error, ValueError, ValidationError) as error:
        msg = "invalid cursor: it was not written by this server"
        raise InvalidCursorError(msg) from error
    return Cursor(hwm=wire.h, key=wire.k, id=wire.i)
