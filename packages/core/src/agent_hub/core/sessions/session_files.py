"""The Files tab: the paths a session touched, with their operations and line counts.

Folded from tool calls (one per tool use id, D16); no file content or diff is stored, only the
path, the operation and the line counts the collector computed before redaction.
"""

from collections.abc import Iterable, Mapping

from agent_hub.core.events.event import EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import resolve_facts
from agent_hub.core.sessions.session import FileOperation, SessionFileChange

_OPERATIONS: Mapping[str, FileOperation] = {
    "Read": "read",
    "NotebookRead": "read",
    "Edit": "edited",
    "MultiEdit": "edited",
    "NotebookEdit": "edited",
    "Write": "written",
}


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def file_operation(stored: StoredEvent) -> FileOperation | None:
    """What a tool call did to its path, or None when it is not a file tool call."""
    event = stored.event
    path = event.payload.get("path")
    if event.type != EventType.TOOL_CALL or not isinstance(path, str) or not path:
        return None
    operation = _OPERATIONS.get(str(event.payload.get("tool")))
    if operation == "written" and event.payload.get("new_file") is True:
        return "created"
    return operation


def fold_session_files(
    events: Iterable[StoredEvent], *, resolved: bool = False
) -> tuple[SessionFileChange, ...]:
    """One entry per (repo, path) a session's file tools touched, sorted by path.

    ``resolved`` says ``events`` are already the fact winners, so they are not resolved again.
    """
    changes: dict[tuple[str | None, str], SessionFileChange] = {}
    for stored in events if resolved else resolve_facts(events).winners:
        operation = file_operation(stored)
        if operation is None:
            continue
        payload = stored.event.payload
        key = (stored.event.repo, str(payload["path"]))
        known = changes.get(key)
        ops = () if known is None else known.ops
        changes[key] = SessionFileChange(
            repo=key[0],
            path=key[1],
            ops=ops if operation in ops else (*ops, operation),
            added=(0 if known is None else known.added) + _count(payload.get("lines_added")),
            removed=(0 if known is None else known.removed) + _count(payload.get("lines_removed")),
            event_ids=(*(() if known is None else known.event_ids), stored.event_id),
        )
    return tuple(changes[key] for key in sorted(changes, key=lambda key: (key[1], key[0] or "")))
