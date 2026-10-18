"""Which file a session's tool call wrote: how a feature record finds the session that wrote it.

A record such as ``brain/features/<slug>/spec.md`` names no session, but the session that wrote
it logged the ``Write`` (or ``Edit``) call with the file's absolute path, its subagents' calls
included. ``wrote`` matches that path by its tail, so a hub-relative path finds it from any
workdir.
"""

from pydantic import JsonValue

# The Claude Code tools that change a file, and the input field naming it.
WRITE_TOOLS: dict[str, str] = {
    "Write": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}


def path_matches(written: str, path: str) -> bool:
    """Whether ``written`` (absolute) is ``path`` (relative, or absolute)."""
    tail = path.lstrip("/")
    return written == path or written.endswith(f"/{tail}")


def wrote(body: dict[str, JsonValue], path: str) -> bool:
    """Whether a ``tool.call`` record's body is a call that changed ``path``."""
    name = body.get("name")
    field = WRITE_TOOLS.get(name) if isinstance(name, str) else None
    tool_input = body.get("input")
    if field is None or not isinstance(tool_input, dict):
        return False
    written = tool_input.get(field)
    return isinstance(written, str) and path_matches(written, path)
