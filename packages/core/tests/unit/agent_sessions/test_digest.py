from pydantic import JsonValue

from agent_hub.core.agent_sessions.agent_session import (
    MAX_CHANGED_FILES,
    MAX_SNIPPET_CHARS,
    ChangedFile,
)
from agent_hub.core.agent_sessions.digest import (
    SessionDigest,
    prompt_snippet,
    reply_snippet,
)
from agent_hub.core.agent_sessions.records import LogRecord, RecordBy, RecordKind
from agent_hub.core.testing.agent_session_rig import START
from agent_hub.core.testing.read_model_builders import an_agent_session

GITHUB_TOKEN = "ghp_" + "Ab1" * 12


def _record(kind: RecordKind, body: dict[str, JsonValue], by: RecordBy = "driver") -> LogRecord:
    return LogRecord(seq=1, at=START, kind=kind, by=by, body=body)


def _call(tool_use_id: str, name: str, **tool_input: JsonValue) -> LogRecord:
    body: dict[str, JsonValue] = {"tool_use_id": tool_use_id, "name": name, "input": tool_input}
    return _record("tool.call", body)


def test_collapses_and_redacts_prompt_when_snipped() -> None:
    snippet = prompt_snippet(f"Fix   the\n\ttest,\n token {GITHUB_TOKEN}  ")

    assert snippet == "Fix the test, token [redacted: github token]"


def test_clips_prompt_to_limit_when_long() -> None:
    snippet = prompt_snippet("word " * 200)

    assert snippet is not None
    assert len(snippet) == MAX_SNIPPET_CHARS
    assert snippet.endswith("…")


def test_answers_none_when_prompt_blank() -> None:
    assert prompt_snippet(" \n\t ") is None


def test_drops_markdown_marks_when_reply_snipped() -> None:
    reply = (
        "## Done\n\n"
        "I **fixed** the `parse_args` bug in *two* places:\n"
        "- `cli.py`\n"
        "* __main__ guard\n"
        "1. a _quick_ test for snake_case_name\n"
        "> quoted\n"
        "```python\nprint(1)\n```"
    )

    assert reply_snippet(reply) == (
        "Done I fixed the parse_args bug in two places: cli.py main guard "
        "a quick test for snake_case_name quoted python print(1)"
    )


def test_redacts_reply_when_secret_in_it() -> None:
    assert reply_snippet(f"Found **{GITHUB_TOKEN}**.") == "Found [redacted: github token]."


def test_takes_latest_prompt_and_reply_when_records_folded() -> None:
    digest = SessionDigest.of_records(
        [
            _record("user.message", {"text": "First."}, by="web"),
            _record("text", {"block": 0, "text": "One."}),
            _record("thinking", {"text": "Hmm."}),
            _record("user.message", {"text": "Second."}, by="web"),
            _record("text", {"block": 0, "text": "Two."}),
            _record("thinking", {"text": "Later thought."}),
        ]
    )

    assert (digest.last_prompt, digest.last_reply) == ("Second.", "Two.")


def test_lists_files_latest_change_first_when_file_tools_called() -> None:
    digest = SessionDigest.of_records(
        [
            _call("t1", "Edit", file_path="/repo/a.py", old_string="a", new_string="b"),
            _call("t2", "Write", file_path="/repo/b.py", content="x"),
            _call("t3", "Read", file_path="/repo/c.py"),
            _call("t4", "NotebookEdit", notebook_path="/repo/n.ipynb", new_source="1"),
            _call("t5", "MultiEdit", file_path="/repo/a.py", edits=[]),
            _call("t6", "Bash", command="touch d.py"),
            _call("t7", "Edit", old_string="a", new_string="b"),
        ]
    )

    assert digest.changed_files() == (
        ChangedFile(path="/repo/a.py", last_change_id="t5"),
        ChangedFile(path="/repo/n.ipynb", last_change_id="t4"),
        ChangedFile(path="/repo/b.py", last_change_id="t2"),
    )


def test_counts_subagent_call_when_parent_given() -> None:
    call = _call("t9", "Write", file_path="/repo/sub.py", content="x")
    nested = call.model_copy(update={"body": call.body | {"parent_tool_use_id": "task-1"}})

    assert SessionDigest.of_records([nested]).changed_files() == (
        ChangedFile(path="/repo/sub.py", last_change_id="t9"),
    )


def test_keeps_most_recent_files_when_over_cap() -> None:
    calls = [
        _call(f"t{number}", "Write", file_path=f"/repo/{number}.py", content="")
        for number in range(MAX_CHANGED_FILES + 5)
    ]

    files = SessionDigest.of_records(calls).changed_files()

    assert len(files) == MAX_CHANGED_FILES
    assert files[0].last_change_id == f"t{MAX_CHANGED_FILES + 4}"
    assert files[-1].last_change_id == "t5"


def test_holds_nothing_pending_when_read_from_session() -> None:
    session = an_agent_session(
        last_prompt="Go.",
        changed_files=(
            ChangedFile(path="/b", last_change_id="t2"),
            ChangedFile(path="/a", last_change_id="t1"),
        ),
    )

    digest = SessionDigest.of(session)

    assert digest.pending() == ({}, 0)
    assert digest.changed_files() == session.changed_files
    digest.add(_call("t3", "Edit", file_path="/a"))
    fields, version = digest.pending()
    assert [item.path for item in fields.get("changed_files", ())] == ["/a", "/b"]
    digest.saved(version)
    assert digest.pending() == ({}, version)


def test_changes_nothing_when_same_call_folded_twice() -> None:
    digest = SessionDigest()
    call = _call("t1", "Edit", file_path="/a")
    digest.add(call)
    version = digest.version

    digest.add(call)

    assert digest.version == version
