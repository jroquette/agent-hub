"""Synthetic Claude Code transcript lines for tests; nothing comes from a real transcript.

Line and block shapes follow the control-plane research (``claude-code-fields.md``); every value
is made up. ``transcript_text`` writes the lines as JSON Lines at test time (no ``*.jsonl`` file
is ever committed).
"""

import json
from collections.abc import Iterable, Sequence
from itertools import count
from typing import Any, Final

TRANSCRIPT_SESSION: Final = "session-1"
TRANSCRIPT_CWD: Final = "/work/demo-api"
TRANSCRIPT_MODEL: Final = "claude-opus-5-5"
_uuids = count(1)

type Line = dict[str, Any]
type Block = dict[str, Any]


def _line(kind: str, body: dict[str, Any], **overrides: Any) -> Line:
    number = next(_uuids)
    line: Line = {
        "type": kind,
        "timestamp": f"2026-10-11T10:{number // 60 % 60:02d}:{number % 60:02d}.000Z",
        "sessionId": TRANSCRIPT_SESSION,
        "uuid": f"uuid-{number:06d}",
        "parentUuid": None,
        "isSidechain": False,
        "cwd": TRANSCRIPT_CWD,
        "gitBranch": "jdoe/dem-7-export",
        "version": "2.1.0",
        "message": body,
    }
    line.update(overrides)
    return line


def a_user_line(text: str = "add the export button", **overrides: Any) -> Line:
    """A user prompt line (string content)."""
    return _line("user", {"role": "user", "content": text}, **overrides)


def a_tool_result_line(
    tool_use_id: str = "toolu_01",
    *,
    content: Any = "all checks passed",
    is_error: bool = False,
    **overrides: Any,
) -> Line:
    """A user line carrying one ``tool_result`` block."""
    block = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }
    return _line("user", {"role": "user", "content": [block]}, **overrides)


def a_usage(
    input_tokens: int = 1200, output_tokens: int = 340, *, cache_read: int = 0, cache_write: int = 0
) -> dict[str, int]:
    """An assistant message's ``usage`` object."""
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write,
    }


def an_assistant_line(
    blocks: Sequence[Block],
    usage: dict[str, int] | None = None,
    message_id: str = "msg_01",
    **overrides: Any,
) -> Line:
    """An assistant line with ``blocks``; lines of one API response share ``message_id``."""
    message = {
        "id": message_id,
        "model": TRANSCRIPT_MODEL,
        "role": "assistant",
        "content": list(blocks),
        "stop_reason": None,
        "usage": usage if usage is not None else a_usage(),
    }
    return _line("assistant", message, **overrides)


def a_text_block(text: str = "Done: the button exports CSV.") -> Block:
    return {"type": "text", "text": text}


def a_thinking_block(thinking: str = "The export needs a header row.") -> Block:
    return {"type": "thinking", "thinking": thinking, "signature": "c2lnbmF0dXJl"}


def a_tool_use_block(
    tool_use_id: str = "toolu_01", name: str = "Bash", tool_input: dict[str, Any] | None = None
) -> Block:
    return {
        "type": "tool_use",
        "id": tool_use_id,
        "name": name,
        "input": tool_input if tool_input is not None else {"command": "make check-fast"},
    }


def transcript_text(lines: Iterable[Line]) -> str:
    """The lines as JSON Lines, one compact object per line, each ending in a newline."""
    return "".join(f"{json.dumps(line, separators=(',', ':'))}\n" for line in lines)
