"""The implementing session's verdict: what ``hub run`` reads from ``claude -p``'s output.

``claude -p`` returns only the last message, so the session's final JSON line is a hint, not
the truth (the old runner's rule): an error result, ``BLOCKED:`` anywhere in the reply or a
``blocked`` verdict stops the run; anything else is done, with the verdict's summary when it
gives one. ``hub run`` then checks the commits on the branch and runs its own gate.
"""

import json
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

# Output that is not claude's JSON result is kept as its last characters.
MAX_RAW_TAIL_CHARS: Final = 2_000
# A reason quotes at most the reply's last characters.
MAX_REASON_TAIL_CHARS: Final = 800
BLOCKED_MARK: Final = "BLOCKED:"
_SESSION = "the implementing session"


class SessionReply(BaseModel):
    """What the implementing ``claude -p`` reported: its result text, cost and turns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_error: bool
    subtype: str | None
    result: str
    cost_usd: float
    turns: int | None


class OutcomeKind(StrEnum):
    """How the implementing session ended, as ``hub run`` reads it."""

    DONE = "done"
    STOPPED = "stopped"
    ERROR = "error"


class Outcome(BaseModel):
    """The session's outcome: for ``done`` the summary (maybe empty), otherwise the reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: OutcomeKind
    text: str


def parse_session_output(text: str) -> SessionReply:
    """``claude --output-format json``'s result; anything else is an error keeping its tail."""
    try:
        value = load_json_bytes(text.encode(), strict=True)
    except InvalidJsonError, UnicodeEncodeError:
        value = None
    if not isinstance(value, dict):
        return SessionReply(
            is_error=True, subtype=None, result=text[-MAX_RAW_TAIL_CHARS:], cost_usd=0.0, turns=None
        )
    result, subtype = value.get("result"), value.get("subtype")
    return SessionReply(
        is_error=value.get("is_error") is True,
        subtype=subtype if isinstance(subtype, str) else None,
        result=result if isinstance(result, str) else "",
        cost_usd=_number(value.get("total_cost_usd")),
        turns=_count(value.get("num_turns")),
    )


def last_json_line(text: str) -> dict[str, object] | None:
    """The last line of ``text`` holding a JSON object, backticks around it ignored.

    A line that only looks like one (``{not json}``) is skipped; a last JSON value that is not
    an object gives None.
    """
    for line in reversed(text.strip().splitlines()):
        candidate = line.strip().strip("`")
        if not (candidate.startswith("{") and candidate.endswith("}")):
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        return value if isinstance(value, dict) else None
    return None


def session_outcome(reply: SessionReply) -> Outcome:
    """Done, stopped or error, by the old runner's rules; reasons quote the reply's tail."""
    tail = reply.result[-MAX_REASON_TAIL_CHARS:]
    if reply.is_error:
        return Outcome(kind=OutcomeKind.ERROR, text=f"{_SESSION} errored ({reply.subtype}): {tail}")
    verdict = last_json_line(reply.result) or {}
    summary = verdict.get("summary")
    text = summary if isinstance(summary, str) else ""
    if BLOCKED_MARK in reply.result or verdict.get("status") == "blocked":
        return Outcome(kind=OutcomeKind.STOPPED, text=f"{_SESSION} stopped: {text or tail}")
    return Outcome(kind=OutcomeKind.DONE, text=text)


def _number(value: JsonValue | None) -> float:
    # A bool is an int to Python, never a cost.
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _count(value: JsonValue | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
