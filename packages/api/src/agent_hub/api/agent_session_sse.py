"""The wire form of one agent session's stream (S4, E8): frames, ids and resume positions.

Pure: no I/O, no clock. Each ``StreamItem`` becomes one ``SseMessage``:

- a persisted ``LogRecord`` is ``event: record.<kind>`` with ``id: <seq>`` and the record as data;
- a ``DeltaFrame`` is ``event: delta`` with ``id: <after_seq>.<index>`` (``after_seq`` the last
  persisted record, ``index`` the delta's place in the open block), so ``seq`` stays gap-free;
- a ``StatusFrame`` is ``event: status`` and a ``ResetFrame`` ``event: reset``, with no id
  (a client resumes only from records and deltas);
- a heartbeat is ``event: heartbeat`` carrying the last id sent.

The data is one JSON line (``SseMessage.encode``): every line break in the text is escaped, so
conversation text can never start a new field or frame. A client resumes with
``Last-Event-ID`` (or ``?after=``) as ``<seq>`` or ``<seq>.<n>``: at most 32 characters,
ASCII digits only; anything else is a ``reset``.
"""

import re
from datetime import datetime
from typing import Final

from pydantic import JsonValue

from agent_hub.api.sse import RETRY, SseMessage
from agent_hub.core.agent_sessions.records import (
    DeltaFrame,
    LogRecord,
    ResetFrame,
    StatusFrame,
    StreamItem,
    StreamPosition,
)
from agent_hub.core.readmodels.view_types import timestamp_text

__all__ = [
    "MAX_POSITION_CHARS",
    "RETRY",
    "UNKNOWN_POSITION",
    "frame",
    "heartbeat_frame",
    "parse_last_event_id",
    "resume_position",
]

MAX_POSITION_CHARS: Final = 32
# The reason of the reset sent for a position that cannot be read.
UNKNOWN_POSITION: Final = "unknown_position"
RECORD_EVENT_PREFIX: Final = "record."
_POSITION = re.compile(r"(?P<seq>[0-9]{1,12})(?:\.(?P<delta>[0-9]{1,6}))?")


def parse_last_event_id(value: str) -> StreamPosition | None:
    """The position a ``Last-Event-ID`` (or ``?after=``) names, or None when malformed."""
    if len(value) > MAX_POSITION_CHARS:
        return None
    matched = _POSITION.fullmatch(value)
    if matched is None:
        return None
    delta = matched["delta"]
    return StreamPosition(seq=int(matched["seq"]), delta=None if delta is None else int(delta))


def resume_position(last_event_id: str | None, *, after: str | None) -> StreamPosition | ResetFrame:
    """Where a stream starts: the header wins over ``?after=``; neither is the start of the
    log; a malformed one is a reset (whether the position exists is the subscription's call)."""
    value = last_event_id if last_event_id is not None else after
    if value is None:
        return StreamPosition(seq=0)
    position = parse_last_event_id(value)
    return ResetFrame(reason=UNKNOWN_POSITION) if position is None else position


def _data(item: DeltaFrame | StatusFrame | ResetFrame) -> dict[str, JsonValue]:
    # The event name says which frame it is, so the ``frame`` tag is not repeated in the data.
    data: dict[str, JsonValue] = item.model_dump(mode="json", exclude={"frame"})
    return data


def frame(item: StreamItem) -> SseMessage:
    """The message of one stream item (module docstring)."""
    if isinstance(item, LogRecord):
        data: dict[str, JsonValue] = item.model_dump(mode="json")
        return SseMessage(f"{RECORD_EVENT_PREFIX}{item.kind}", data, id=str(item.seq))
    if isinstance(item, DeltaFrame):
        return SseMessage("delta", _data(item), id=f"{item.after_seq}.{item.index}")
    if isinstance(item, StatusFrame):
        return SseMessage("status", _data(item))
    return SseMessage("reset", _data(item))


def heartbeat_frame(now: datetime, *, last_id: str | None) -> SseMessage:
    """The heartbeat: when it was sent, with the last id sent so a reconnect resumes exactly."""
    return SseMessage("heartbeat", {"at": timestamp_text(now)}, id=last_id)
