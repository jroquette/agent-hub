from datetime import timedelta
from itertools import count

from agent_hub.core.sessions.session_files import fold_session_files
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_session_events,
    as_stored,
    shuffled,
    stored_event_id,
    with_transcript_copies,
)

_MINUTES = count()


def _call(tool: str, path: str, **payload: object) -> object:
    return an_event(
        type="tool.call",
        timestamp=SCENARIO_START + timedelta(minutes=next(_MINUTES)),
        repo="demo-api",
        payload={"tool": tool, "tool_use_id": f"toolu_{tool}_{path}", "path": path} | payload,
    )


def test_lists_paths_with_ops_and_line_counts_when_session_edits_files() -> None:
    events = as_stored(
        [
            _call("Read", "src/app.py"),
            _call("Edit", "src/app.py", lines_added=3, lines_removed=1),
            _call("Write", "src/new.py", lines_added=10, lines_removed=0, new_file=True),
            _call("Write", "README.md", lines_added=2, lines_removed=5, new_file=False),
            _call("Bash", "ignored", command="ls"),
        ]
    )

    files = fold_session_files(events)

    assert [(item.path, item.ops, item.added, item.removed) for item in files] == [
        ("README.md", ("written",), 2, 5),
        ("src/app.py", ("read", "edited"), 3, 1),
        ("src/new.py", ("created",), 10, 0),
    ]
    assert files[1].event_ids == (stored_event_id(1), stored_event_id(2))
    assert files[1].repo == "demo-api"


def test_counts_each_tool_use_once_when_transcript_copies_exist() -> None:
    plain = fold_session_files(as_stored(a_session_events()))
    copied = as_stored(with_transcript_copies(a_session_events()))

    files = fold_session_files(copied)

    assert [(item.path, item.ops, item.added, item.removed) for item in files] == [
        (item.path, item.ops, item.added, item.removed) for item in plain
    ]
    assert files == fold_session_files(shuffled(copied, 3))


def test_lists_nothing_when_no_file_tool_ran() -> None:
    assert (
        fold_session_files(as_stored(a_session_events(tools=[("Bash", {"command": "ls"})]))) == ()
    )
