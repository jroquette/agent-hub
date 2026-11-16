"""The text of log records: the stored (redacted, clipped) copy, input summaries and sizes.

Pure. ``AgentSessionControl`` keeps two copies of each record (P8): the live one, raw, for the
browser that is connected now, and the stored one, ``redacted(record)``, for the store and every
replay (E9). Redaction uses the ADR 0019 rules (``redact_text``) on every string of the body,
keys included; clipping comes after redaction and never cuts inside a marker, so a cut never
leaves a secret's prefix no rule would recognise.

Sizes are UTF-8 bytes: ``text_bytes`` is the size of a body's compact JSON, which the log caps
count; summaries and errors are clipped to the limits' byte sizes, titles to 200 characters.
"""

import json
from collections.abc import Callable, Mapping
from typing import Final

from pydantic import JsonValue

from agent_hub.core.agent_sessions.agent_session import MAX_TITLE_CHARS
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.records import LogRecord
from agent_hub.core.redaction.redact import ELLIPSIS, clip, redact_text, redact_value

TITLE_CHARS: Final = MAX_TITLE_CHARS
# The input field that says what a tool use does, per tool; other tools show their input as JSON.
_SUMMARY_FIELDS: Final = {
    "Bash": "command",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "Read": "file_path",
    "NotebookEdit": "notebook_path",
    "WebFetch": "url",
    "WebSearch": "query",
    "Grep": "pattern",
    "Glob": "pattern",
    "Task": "description",
    "Agent": "description",
    "ExitPlanMode": "plan",
}
_ELLIPSIS_BYTES: Final = len(ELLIPSIS.encode())

type _Cut = Callable[[str], str]


def text_bytes(body: Mapping[str, JsonValue]) -> int:
    """The UTF-8 size of ``body`` as compact JSON: what a record adds to the log's text."""
    return len(compact_json(body).encode())


def compact_json(value: JsonValue | Mapping[str, JsonValue]) -> str:
    """``value`` as compact JSON with sorted keys and characters kept as they are."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def clip_bytes(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` UTF-8 bytes, ending in ``…`` when cut; a cut never
    falls inside a redaction marker."""
    encoded = text.encode()
    if len(encoded) <= limit:
        return text
    if limit < _ELLIPSIS_BYTES:
        return ""
    kept = encoded[: limit - _ELLIPSIS_BYTES].decode(errors="ignore")
    return clip(text, len(kept) + len(ELLIPSIS))


def summary(
    tool: str, tool_input: Mapping[str, JsonValue], *, limit: int = 4096, redact: bool = False
) -> str:
    """What a tool use does, in one text of at most ``limit`` bytes: the command, the path or
    the URL for the known tools, else the input as JSON. ``redact`` redacts it before the clip
    (the stored copy, E10); the live copy is raw."""
    field = _SUMMARY_FIELDS.get(tool)
    value = tool_input.get(field) if field is not None else None
    text = value if isinstance(value, str) else compact_json(tool_input)
    if redact:
        text = redact_text(text)
    return clip_bytes(text, limit)


def title(text: str) -> str:
    """A session title as stored and shown: redacted, at most 200 characters."""
    return clip(redact_text(text), TITLE_CHARS)


def redacted(record: LogRecord, limits: SessionLimits | None = None) -> LogRecord:
    """The stored copy of ``record``: every string redacted, the permission summary and the
    error message clipped to their byte limits, a title to 200 characters, and ``text_bytes``
    counted again."""
    limits = limits or SessionLimits()
    body = _redacted_body(record.body)
    if record.kind == "permission.request":
        _clip_field(body, "summary", lambda text: clip_bytes(text, limits.summary_bytes))
    if record.kind == "error":
        _clip_field(body, "message", lambda text: clip_bytes(text, limits.error_bytes))
    _clip_field(body, "title", lambda text: clip(text, TITLE_CHARS))
    return record.model_copy(update={"body": body, "text_bytes": text_bytes(body)})


def _redacted_body(body: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {redact_text(key): redact_value(value) for key, value in body.items()}


def _clip_field(body: dict[str, JsonValue], key: str, cut: _Cut) -> None:
    value = body.get(key)
    if isinstance(value, str):
        body[key] = cut(value)
