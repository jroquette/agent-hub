"""The metadata a tool call keeps (D11): never a body, only names, sizes and short texts.

Shared by the hook mapper (PreToolUse ``tool_input``) and the transcript parser (``tool_use``
``input``): both carry the same tool input, whose key names live in this module's table only.
Line counts are taken before redaction; every kept text is redacted, then clipped.
"""

import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Final
from urllib.parse import urlsplit

from agent_hub.core.json_form import JsonValue
from agent_hub.core.redaction.redact import clip, redact_text

# Tool input keys (Claude Code's built-in tools).
FILE_PATH: Final = "file_path"
NOTEBOOK_PATH: Final = "notebook_path"
OLD_STRING: Final = "old_string"
NEW_STRING: Final = "new_string"
EDITS: Final = "edits"
CONTENT: Final = "content"
COMMAND: Final = "command"
PATTERN: Final = "pattern"
SEARCH_PATH: Final = "path"
URL: Final = "url"
SUBAGENT_TYPE: Final = "subagent_type"
DESCRIPTION: Final = "description"

EDIT_TOOLS: Final = frozenset({"Edit", "MultiEdit"})
WRITE_TOOL: Final = "Write"
PATH_TOOLS: Final = frozenset({"Read", "NotebookEdit", "NotebookRead"})
SEARCH_TOOLS: Final = frozenset({"Grep", "Glob"})
AGENT_TOOLS: Final = frozenset({"Agent", "Task"})
MCP_PREFIX: Final = "mcp__"

COMMAND_LIMIT: Final = 500
PATTERN_LIMIT: Final = 200
DESCRIPTION_LIMIT: Final = 80
TITLE_LIMIT: Final = 120
ERROR_LINE_LIMIT: Final = 200
NAME_LIMIT: Final = 80
WORKTREES: Final = (".claude", "worktrees")
INBOX: Final = ("brain", "_inbox")
# A prompt's slash command: typed first, or wrapped by Claude Code in its transcript.
_SLASH_COMMAND: Final = re.compile(r"(?:<command-name>)?(/[A-Za-z0-9_.:\-]+)")
_HEADING: Final = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)

type Payload = dict[str, JsonValue]
type ToolInput = Mapping[str, JsonValue]


def short_text(value: str, limit: int) -> str:
    """``value`` redacted, then clipped to ``limit`` characters (D11's allowed short texts)."""
    return clip(redact_text(value), limit)


def prompt_command(prompt: str) -> str | None:
    """The ``/name`` a prompt starts with, never its arguments; None for plain text."""
    found = _SLASH_COMMAND.match(prompt.lstrip())
    return None if found is None else short_text(found.group(1), NAME_LIMIT)


def first_line(text: str) -> str:
    """The first non-blank line of an error, redacted and clipped (D11)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return short_text(lines[0] if lines else "", ERROR_LINE_LIMIT)


def tool_call_payload(
    tool_name: str, tool_input: ToolInput, *, repo_root: PurePosixPath | None
) -> Payload:
    """The D11 keys of one call of ``tool_name``; an unknown tool or malformed input keeps none."""
    if tool_name in EDIT_TOOLS or tool_name == WRITE_TOOL:
        return _file_change(tool_name, tool_input, repo_root=repo_root)
    if tool_name in PATH_TOOLS:
        return _path_only(tool_input, repo_root=repo_root)
    if tool_name == "Bash":
        return _text_key(tool_input, COMMAND, COMMAND_LIMIT)
    if tool_name in SEARCH_TOOLS:
        return _search(tool_input, repo_root=repo_root)
    if tool_name == "WebFetch":
        return _web_fetch(tool_input)
    if tool_name.startswith(MCP_PREFIX):
        return _mcp(tool_name, tool_input)
    if tool_name in AGENT_TOOLS:
        return _agent(tool_input)
    return {}


def repo_root_of(cwd: str | None, repo: str | None) -> PurePosixPath | None:
    """The checkout of ``repo`` that holds ``cwd``: its main folder or one of its worktrees."""
    if cwd is None or repo is None:
        return None
    parts = PurePosixPath(cwd).parts
    indexes = [index for index, part in enumerate(parts) if part == repo]
    if not indexes:
        return None
    end = indexes[-1] + 1
    if parts[end : end + 2] == WORKTREES and len(parts) > end + 2:
        end += 3
    return PurePosixPath(*parts[:end])


def shown_path(path: str, *, repo_root: PurePosixPath | None) -> str:
    """``path`` relative to ``repo_root`` when under it, else as given."""
    if repo_root is not None:
        candidate = PurePosixPath(path)
        if candidate.is_relative_to(repo_root):
            return str(candidate.relative_to(repo_root)) or "."
    return path


def output_bytes(output: JsonValue) -> int | None:
    """The UTF-8 size of a tool's output (its compact JSON when not text); None when absent."""
    if output is None:
        return None
    text = output if isinstance(output, str) else json.dumps(output, separators=(",", ":"))
    return len(text.encode("utf-8", errors="replace"))


def line_count(text: str) -> int:
    """Lines in ``text``; a last line without a newline counts."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def learning_proposal(tool_name: str, tool_input: ToolInput, *, tool_use_id: str) -> Payload | None:
    """A Write of a note under ``brain/_inbox/``: the proposal's id, title and target."""
    path = tool_input.get(FILE_PATH)
    content = tool_input.get(CONTENT)
    if tool_name != WRITE_TOOL or not isinstance(path, str) or not isinstance(content, str):
        return None
    parts = PurePosixPath(path).parts
    starts = [i for i in range(len(parts) - 2) if parts[i : i + 2] == INBOX]
    if not starts:
        return None
    heading = _HEADING.search(content)
    title = heading.group(1) if heading else PurePosixPath(path).stem
    return {
        "proposal": tool_use_id,
        "text": short_text(title, TITLE_LIMIT),
        "target": str(PurePosixPath(*parts[starts[-1] :])),
    }


def _file_change(
    tool_name: str, tool_input: ToolInput, *, repo_root: PurePosixPath | None
) -> Payload:
    payload = _path_only(tool_input, repo_root=repo_root)
    if not payload:
        return {}
    if tool_name == WRITE_TOOL:
        content = tool_input.get(CONTENT)
        if isinstance(content, str):
            payload["lines_added"] = line_count(content)
        return payload
    added, removed = _edit_lines(tool_input)
    payload |= {"lines_added": added, "lines_removed": removed, "new_file": False}
    return payload


def _edit_lines(tool_input: ToolInput) -> tuple[int, int]:
    edits = tool_input.get(EDITS)
    pairs = [edit for edit in edits if isinstance(edit, dict)] if isinstance(edits, list) else []
    if not pairs:
        pairs = [dict(tool_input)]
    added = sum(_lines_of(edit.get(NEW_STRING)) for edit in pairs)
    removed = sum(_lines_of(edit.get(OLD_STRING)) for edit in pairs)
    return added, removed


def _lines_of(value: JsonValue) -> int:
    return line_count(value) if isinstance(value, str) else 0


def _path_only(tool_input: ToolInput, *, repo_root: PurePosixPath | None) -> Payload:
    path = tool_input.get(FILE_PATH, tool_input.get(NOTEBOOK_PATH))
    if not isinstance(path, str) or not path:
        return {}
    return {"path": shown_path(path, repo_root=repo_root)}


def _text_key(tool_input: ToolInput, key: str, limit: int) -> Payload:
    value = tool_input.get(key)
    return {key: short_text(value, limit)} if isinstance(value, str) else {}


def _search(tool_input: ToolInput, *, repo_root: PurePosixPath | None) -> Payload:
    payload = _text_key(tool_input, PATTERN, PATTERN_LIMIT)
    path = tool_input.get(SEARCH_PATH)
    if isinstance(path, str) and path:
        payload["path"] = shown_path(path, repo_root=repo_root)
    return payload


def _web_fetch(tool_input: ToolInput) -> Payload:
    url = tool_input.get(URL)
    if not isinstance(url, str):
        return {}
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return {}
    if not parts.scheme or not host:
        return {}
    port = f":{parts.port}" if _has_port(parts.netloc) else ""
    return {"url": short_text(f"{parts.scheme}://{host}{port}{parts.path}", COMMAND_LIMIT)}


def _has_port(netloc: str) -> bool:
    host_and_port = netloc.rpartition("@")[2]
    return bool(re.search(r":\d+$", host_and_port))


def _mcp(tool_name: str, tool_input: ToolInput) -> Payload:
    server, separator, tool = tool_name.removeprefix(MCP_PREFIX).partition("__")
    if not separator or not server or not tool:
        return {}
    keys: list[JsonValue] = [short_text(key, NAME_LIMIT) for key in sorted(tool_input)]
    return {
        "mcp_server": short_text(server, NAME_LIMIT),
        "mcp_tool": short_text(tool, NAME_LIMIT),
        "arg_keys": keys,
    }


def _agent(tool_input: ToolInput) -> Payload:
    payload: Payload = {}
    for key in (SUBAGENT_TYPE, DESCRIPTION):
        payload |= _text_key(tool_input, key, DESCRIPTION_LIMIT)
    return payload
