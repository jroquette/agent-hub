import json

from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.record_text import (
    TITLE_CHARS,
    clip_bytes,
    redacted,
    summary,
    text_bytes,
    title,
)
from agent_hub.core.testing.read_model_builders import a_log_record

# Synthetic secrets, built at run time so no scanner mistakes them for real ones.
GITHUB_TOKEN = "ghp_" + "Ab1" * 12
LINEAR_KEY = "lin_api_" + "Zx9" * 10


def test_redacts_token_when_tool_result_holds_one() -> None:
    record = a_log_record(
        "tool.result",
        body={"tool_use_id": "toolu_01", "content": f"token {GITHUB_TOKEN}", "is_error": False},
    )

    stored = redacted(record)

    assert stored.body["content"] == "token [redacted: github token]"
    assert stored.text_bytes == text_bytes(stored.body)
    assert GITHUB_TOKEN not in json.dumps(stored.body)


def test_redacts_nested_strings_when_tool_call_input_holds_secret() -> None:
    record = a_log_record(
        "tool.call",
        body={
            "tool_use_id": "toolu_02",
            "name": "Bash",
            "input": {"command": f"curl -H 'x: {LINEAR_KEY}'", "args": [LINEAR_KEY]},
            "parent_tool_use_id": None,
        },
    )

    stored = redacted(record)

    assert LINEAR_KEY not in json.dumps(stored.body)
    assert stored.body["name"] == "Bash"


def test_clips_summary_when_input_large() -> None:
    record = a_log_record(
        "permission.request",
        body={
            "request_id": "req-1",
            "tool": "Bash",
            "request_kind": "tool",
            "summary": "é" * 5000,
            "suggestions": [],
        },
    )

    stored = redacted(record, SessionLimits(summary_bytes=4096))

    clipped = stored.body["summary"]
    assert isinstance(clipped, str)
    assert len(clipped.encode()) <= 4096
    assert clipped.endswith("…")


def test_clips_error_when_message_large() -> None:
    record = a_log_record("error", body={"message": "x" * 5000})

    stored = redacted(record, SessionLimits(error_bytes=2048))

    message = stored.body["message"]
    assert isinstance(message, str)
    assert len(message.encode()) <= 2048


def test_keeps_marker_whole_when_clip_falls_inside_it() -> None:
    text = "a" * 10 + "[redacted: github token]" + "b" * 10

    clipped = clip_bytes(text, 20)

    assert clipped == "a" * 10 + "…"


def test_keeps_text_when_under_limit() -> None:
    assert clip_bytes("héllo", 6) == "héllo"


def test_summarizes_command_when_tool_is_bash() -> None:
    assert summary("Bash", {"command": "git status", "description": "Show it"}) == "git status"


def test_summarizes_path_when_tool_edits_file() -> None:
    assert summary("Edit", {"file_path": "src/app.py", "old_string": "a"}) == "src/app.py"
    assert summary("WebFetch", {"url": "https://example.org/x"}) == "https://example.org/x"


def test_summarizes_json_when_tool_unknown() -> None:
    assert summary("mcp__x__y", {"b": 1, "a": "z"}) == '{"a":"z","b":1}'


def test_redacts_before_clip_when_summary_stored() -> None:
    long_command = "echo " + "x" * 30 + " " + GITHUB_TOKEN

    stored = summary("Bash", {"command": long_command}, limit=40, redact=True)
    raw = summary("Bash", {"command": long_command}, limit=40)

    assert "ghp_" not in stored
    assert len(raw.encode()) <= 40


def test_redacts_and_clips_title_when_long() -> None:
    clipped = title(GITHUB_TOKEN + " " + "t" * 400)

    assert clipped.startswith("[redacted: github token]")
    assert len(clipped) <= TITLE_CHARS
