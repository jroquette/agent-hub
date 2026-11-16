"""Opaque snapshot cursors: ``{hwm, key, id}`` as base64url JSON, 512 characters at most.

A list read folds the events up to a high-water mark and pages through the sorted result; the
cursor carries that mark, the sort key of the last item returned and its id, so the next page
folds the same events (later appends wait for a fresh first page) and starts right after that
item: no item repeats and none is skipped (AC-200.32).

When the key and id do not fit (long ids or labels, S2), the cursor carries the mark and a
digest of the last item's id instead: the next page starts right after the item with that
digest in the same snapshot.
"""

import base64
import binascii
import hashlib
import json
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from agent_hub.core.errors import AgentHubError
from agent_hub.core.readmodels.page import MAX_CURSOR_CHARS

type CursorKeyPart = StrictInt | StrictStr | None


class InvalidCursorError(AgentHubError):
    """A cursor that this server did not write, or that was damaged (the API answers 400)."""


DIGEST_CHARS = 32
_DIGEST_PATTERN = rf"^[0-9a-f]{{{DIGEST_CHARS}}}$"


def id_digest(item_id: str) -> str:
    """The digest a compact cursor names an item by: 32 hex digits of its id's SHA-256."""
    return hashlib.sha256(item_id.encode("utf-8", errors="surrogatepass")).hexdigest()[
        :DIGEST_CHARS
    ]


class Cursor(BaseModel):
    """Where the next page starts: the snapshot's high-water mark and the last item's key.

    Either ``key`` and ``id`` name the last item, or (compact form) ``id_digest`` does, with
    ``id`` None and ``key`` empty.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hwm: Annotated[int, Field(ge=0)]
    key: tuple[CursorKeyPart, ...]
    id: str | None = None
    id_digest: Annotated[str | None, Field(pattern=_DIGEST_PATTERN)] = None

    @model_validator(mode="after")
    def _one_way_to_name_the_item(self) -> Self:
        if (self.id is None) == (self.id_digest is None):
            msg = "a cursor names its last item by id or by id_digest, exactly one"
            raise ValueError(msg)
        return self


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    h: Annotated[StrictInt, Field(ge=0)]
    k: tuple[CursorKeyPart, ...]
    i: StrictStr | None = None
    d: Annotated[StrictStr | None, Field(pattern=_DIGEST_PATTERN)] = None


def encode_cursor(cursor: Cursor) -> str:
    """``cursor`` as opaque text of at most 512 characters, compact when the full one is longer."""
    if cursor.id is not None:
        text = _text(_Wire(h=cursor.hwm, k=cursor.key, i=cursor.id))
        if len(text) <= MAX_CURSOR_CHARS:
            return text
    digest = cursor.id_digest if cursor.id is None else id_digest(cursor.id)
    return _text(_Wire(h=cursor.hwm, k=(), d=digest))


def _text(wire: _Wire) -> str:
    raw = json.dumps(wire.model_dump(exclude_none=True), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(text: str) -> Cursor:
    """The cursor ``encode_cursor`` wrote as ``text``; ``InvalidCursorError`` for anything else."""
    if not text or len(text) > MAX_CURSOR_CHARS:
        msg = f"invalid cursor: expected 1 to {MAX_CURSOR_CHARS} characters"
        raise InvalidCursorError(msg)
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        wire = _Wire.model_validate_json(raw)
        return Cursor(hwm=wire.h, key=wire.k, id=wire.i, id_digest=wire.d)
    except (binascii.Error, ValueError, ValidationError) as error:
        msg = "invalid cursor: it was not written by this server"
        raise InvalidCursorError(msg) from error
