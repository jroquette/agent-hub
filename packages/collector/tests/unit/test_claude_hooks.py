"""The hook mapper (D8, E2-E4): one table row per hook, keys exactly as "Payload kept" says."""

import hashlib
import json
from typing import Any

import pytest

from agent_hub.collector.claude_hooks import ClaudeHookMapper
from agent_hub.core.events.event import Event
from agent_hub.core.ingestion.hook_envelope import HookDecision
from agent_hub.core.ingestion.ingestion_ports import TranscriptRef
from agent_hub.core.testing.hook_inputs import (
    HOOK_CWD,
    HOOK_EVENT_NAMES,
    HOOK_SESSION,
    HOOK_TRANSCRIPT,
    SUBAGENT_TRANSCRIPT,
    a_hook_input,
    an_envelope,
)

SENT_AT = "2026-10-11T10:00:00.250000+00:00"


def _h16(hook: dict[str, Any]) -> str:
    canonical = json.dumps(hook, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _only(hook: dict[str, Any], **envelope: Any) -> Event:
    mapping = ClaudeHookMapper().map(an_envelope(hook, **envelope))
    [event] = mapping.events
    return event


def test_maps_session_start_when_startup() -> None:
    hook = a_hook_input("SessionStart")

    event = _only(hook)

    assert event.type == "session.start"
    assert event.source == "claude_code"
    assert event.source_id == f"{HOOK_SESSION}:SessionStart:{SENT_AT}:{_h16(hook)}"
    assert event.payload == {
        "trigger": "startup",
        "cwd": HOOK_CWD,
        "permission_mode": "default",
        "model": "claude-opus-5-5",
        "transcript_path": HOOK_TRANSCRIPT,
    }
    assert (event.project, event.session, event.repo, event.agent) == (
        "demo",
        HOOK_SESSION,
        "demo-api",
        "main",
    )
    assert (event.workflow, event.step) == (None, None)
    assert event.timestamp.isoformat() == SENT_AT


def test_keeps_fork_trigger_when_session_forked() -> None:
    event = _only(a_hook_input("SessionStart", source="fork", model=...))

    assert event.payload["trigger"] == "fork"
    assert "model" not in event.payload


def test_maps_prompt_to_size_and_command_name_when_user_prompt_submit() -> None:
    hook = a_hook_input("UserPromptSubmit", prompt="/feature:plan add the SENTINEL export")

    event = _only(hook)

    assert event.type == "message"
    assert event.source_id == f"{HOOK_SESSION}:UserPromptSubmit:{SENT_AT}:{_h16(hook)}"
    assert event.payload == {"role": "user", "chars": 37, "slash_command": "/feature:plan"}
    assert "SENTINEL" not in event.model_dump_json()


def test_leaves_command_out_when_prompt_is_plain_text() -> None:
    event = _only(a_hook_input("UserPromptSubmit", prompt="fix it"))

    assert event.payload == {"role": "user", "chars": 6}


def test_maps_tool_call_with_metadata_when_pre_tool_use() -> None:
    event = _only(a_hook_input("PreToolUse"))

    assert event.type == "tool.call"
    assert event.source_id == f"{HOOK_SESSION}:PreToolUse:toolu_01"
    assert event.payload == {
        "tool": "Bash",
        "tool_use_id": "toolu_01",
        "command": "make check-fast",
    }


def test_keeps_repo_relative_path_when_edit_in_repo() -> None:
    hook = a_hook_input(
        "PreToolUse",
        tool_name="Edit",
        tool_input={
            "file_path": f"{HOOK_CWD}/src/app.py",
            "old_string": "SENTINEL old",
            "new_string": "SENTINEL\nnew",
        },
    )

    event = _only(hook)

    assert event.payload == {
        "tool": "Edit",
        "tool_use_id": "toolu_01",
        "path": "src/app.py",
        "lines_added": 2,
        "lines_removed": 1,
        "new_file": False,
    }


def test_also_proposes_learning_when_write_under_brain_inbox() -> None:
    hook = a_hook_input(
        "PreToolUse",
        tool_name="Write",
        tool_input={"file_path": "/work/demo-hub/brain/_inbox/note.md", "content": "# Idea\nbody"},
    )

    events = ClaudeHookMapper().map(an_envelope(hook)).events

    assert [event.type for event in events] == ["tool.call", "learning.proposed"]
    learning = events[1]
    assert learning.source_id == f"{HOOK_SESSION}:PreToolUse:toolu_01:learning"
    assert learning.payload == {
        "proposal": "toolu_01",
        "text": "Idea",
        "target": "brain/_inbox/note.md",
        "author": "main",
    }


def test_maps_ok_result_when_post_tool_use() -> None:
    hook = a_hook_input("PostToolUse")

    event = _only(hook)

    assert event.type == "tool.result"
    assert event.source_id == f"{HOOK_SESSION}:PostToolUse:toolu_01"
    output = json.dumps(hook["tool_response"], separators=(",", ":"))
    assert event.payload == {
        "tool": "Bash",
        "tool_use_id": "toolu_01",
        "status": "ok",
        "duration_ms": 1250,
        "output_bytes": len(output),
    }


def test_maps_error_line_when_post_tool_use_failure() -> None:
    event = _only(a_hook_input("PostToolUseFailure", duration_ms=80))

    assert event.type == "tool.result"
    assert event.source_id == f"{HOOK_SESSION}:PostToolUseFailure:toolu_01"
    assert event.payload == {
        "tool": "Bash",
        "tool_use_id": "toolu_01",
        "status": "error",
        "duration_ms": 80,
        "error_line": "Exit code 2",
    }


def test_says_interrupted_when_failure_is_interrupt() -> None:
    event = _only(a_hook_input("PostToolUseFailure", is_interrupt=True))

    assert event.payload["error_line"] == "interrupted"


def test_maps_permission_gate_when_notification_is_permission_prompt() -> None:
    hook = a_hook_input("Notification")

    event = _only(hook)

    source_id = f"{HOOK_SESSION}:Notification:{SENT_AT}:{_h16(hook)}"
    assert event.type == "gate.request"
    assert event.source_id == source_id
    assert event.payload == {"gate_id": source_id, "kind": "permission"}


def test_maps_session_end_and_main_transcript_when_session_ends() -> None:
    hook = a_hook_input("SessionEnd")

    mapping = ClaudeHookMapper().map(an_envelope(hook))

    [event] = mapping.events
    assert event.type == "session.end"
    assert event.source_id == f"{HOOK_SESSION}:SessionEnd:{SENT_AT}:{_h16(hook)}"
    assert event.payload == {"end_reason": "prompt_input_exit", "outcome": "stopped"}
    assert mapping.transcript == TranscriptRef(
        project="demo",
        repo="demo-api",
        agent="main",
        session=HOOK_SESSION,
        path=HOOK_TRANSCRIPT,
        kind="main",
    )


@pytest.mark.parametrize(
    ("reason", "outcome"),
    [("clear", "stopped"), ("logout", "stopped"), ("resume", None), ("other", None)],
)
def test_derives_outcome_when_session_end_reason_given(reason: str, outcome: str | None) -> None:
    event = _only(a_hook_input("SessionEnd", reason=reason))

    assert event.payload == {"end_reason": reason, "outcome": outcome}


def test_returns_main_transcript_and_no_event_when_stop() -> None:
    mapping = ClaudeHookMapper().map(an_envelope(a_hook_input("Stop")))

    assert mapping.events == ()
    assert mapping.transcript == TranscriptRef(
        project="demo",
        repo="demo-api",
        agent="main",
        session=HOOK_SESSION,
        path=HOOK_TRANSCRIPT,
        kind="main",
    )


def test_returns_subagent_transcript_and_no_event_when_subagent_stop() -> None:
    mapping = ClaudeHookMapper().map(an_envelope(a_hook_input("SubagentStop")))

    assert mapping.events == ()
    assert mapping.transcript == TranscriptRef(
        project="demo",
        repo="demo-api",
        agent="Explore",
        session=HOOK_SESSION,
        path=SUBAGENT_TRANSCRIPT,
        kind="subagent",
    )


@pytest.mark.parametrize(
    "hook",
    [
        a_hook_input("SubagentStart"),
        a_hook_input("PreCompact"),
        a_hook_input("Notification", notification_type="idle_prompt"),
        a_hook_input("Notification", notification_type=...),
        a_hook_input("Stop", hook_event_name="Unknown"),
    ],
    ids=["subagent_start", "pre_compact", "idle_notification", "untyped_notification", "unknown"],
)
def test_yields_no_event_when_hook_is_trigger_only(hook: dict[str, Any]) -> None:
    mapping = ClaudeHookMapper().map(an_envelope(hook))

    assert mapping.events == ()
    assert mapping.transcript is None


def test_attributes_subagent_when_hook_comes_from_subagent() -> None:
    hook = a_hook_input("PreToolUse", agent_id="agent-7", agent_type="Explore")

    event = _only(hook)

    assert event.agent == "Explore"
    assert event.payload["agent_id"] == "agent-7"


def test_attributes_run_step_and_attempt_when_envelope_from_hub_run() -> None:
    event = _only(a_hook_input("PreToolUse"), run="1a2b3c4d", step="implement", attempt=2)

    assert (event.workflow, event.step) == ("issue-to-pr", "implement")
    assert event.payload["run"] == "1a2b3c4d"
    assert event.payload["attempt"] == 2


def test_maps_denied_result_when_guard_denies() -> None:
    hook = a_hook_input("PreToolUse")
    decision = HookDecision(by="guard", kind="deny", rule="push-to-main")

    event = _only(hook, decision=decision)

    assert event.type == "tool.result"
    assert event.source_id == f"{HOOK_SESSION}:guard:toolu_01"
    assert event.payload == {
        "tool": "Bash",
        "tool_use_id": "toolu_01",
        "status": "denied",
        "rule": "push-to-main",
        "hook": "guard",
    }


def test_maps_guard_ask_gate_when_guard_asks_decision() -> None:
    hook = a_hook_input(
        "PreToolUse",
        tool_name="Edit",
        tool_input={
            "file_path": f"{HOOK_CWD}/docs/adr/0017.md",
            "old_string": "a",
            "new_string": "b",
        },
    )
    decision = HookDecision(by="guard", kind="ask", rule="ask-before-edit")

    event = _only(hook, decision=decision)

    assert event.type == "gate.request"
    assert event.source_id == f"{HOOK_SESSION}:guard_ask:toolu_01"
    assert event.payload == {
        "gate_id": "toolu_01",
        "kind": "guard_ask",
        "path": "docs/adr/0017.md",
        "rule": "ask-before-edit",
    }


def test_maps_failed_stop_gate_when_stop_gate_blocks_decision() -> None:
    hook = a_hook_input("Stop")
    decision = HookDecision(by="stop_gate", kind="block", command="make check-fast", exit_code=2)

    mapping = ClaudeHookMapper().map(an_envelope(hook, decision=decision))

    [event] = mapping.events
    source_id = f"{HOOK_SESSION}:stop_gate:{SENT_AT}:{_h16(hook)}"
    assert event.type == "gate.result"
    assert event.source_id == source_id
    assert event.payload == {
        "gate_id": source_id,
        "kind": "stop_gate",
        "command": "make check-fast",
        "exit_code": 2,
        "result": "failed",
    }
    assert mapping.transcript is None


def test_falls_back_to_hash_when_guard_decision_has_no_tool_use_id() -> None:
    hook = a_hook_input("PreToolUse", tool_use_id=...)

    event = _only(hook, decision=HookDecision(by="guard", kind="deny"))

    assert event.source_id == f"{HOOK_SESSION}:guard:{SENT_AT}:{_h16(hook)}"
    assert event.payload == {"tool": "Bash", "status": "denied", "hook": "guard"}


@pytest.mark.parametrize("name", HOOK_EVENT_NAMES)
def test_never_raises_when_every_optional_key_missing(name: str) -> None:
    hook = {"hook_event_name": name, "session_id": HOOK_SESSION}

    mapping = ClaudeHookMapper().map(an_envelope(hook))

    for event in mapping.events:
        assert event.session == HOOK_SESSION
    assert mapping.transcript is None


@pytest.mark.parametrize("name", HOOK_EVENT_NAMES)
def test_never_raises_when_values_have_wrong_types(name: str) -> None:
    hook = {key: [1, {"x": None}] for key in a_hook_input(name)}
    hook["hook_event_name"] = name
    hook["session_id"] = HOOK_SESSION

    mapping = ClaudeHookMapper().map(an_envelope(hook))

    assert mapping.transcript is None


def test_yields_nothing_when_session_id_missing() -> None:
    mapping = ClaudeHookMapper().map(an_envelope(a_hook_input("PreToolUse", session_id=...)))

    assert mapping.events == ()
    assert mapping.transcript is None


# S1: the sensor sends sizes in place of bodies; the mapper reads both shapes alike.
def test_maps_prompt_size_and_command_when_sensor_sent_reduced_prompt() -> None:
    hook = a_hook_input(
        "UserPromptSubmit", prompt=..., prompt_chars=37, prompt_slash_command="/feature:plan"
    )

    event = _only(hook)

    assert event.payload == {"role": "user", "chars": 37, "slash_command": "/feature:plan"}


def test_maps_line_counts_when_sensor_sent_reduced_edit() -> None:
    reduced = {"file_path": f"{HOOK_CWD}/src/app.py", "old_string_lines": 1, "new_string_lines": 2}
    edits = {
        "file_path": f"{HOOK_CWD}/src/app.py",
        "edits": [
            {"old_string_lines": 1, "new_string_lines": 2},
            {"old_string_lines": 3, "new_string_lines": 0},
        ],
    }

    edit = _only(a_hook_input("PreToolUse", tool_name="Edit", tool_input=reduced))
    multi = _only(a_hook_input("PreToolUse", tool_name="MultiEdit", tool_input=edits))

    assert (edit.payload["lines_added"], edit.payload["lines_removed"]) == (2, 1)
    assert (multi.payload["lines_added"], multi.payload["lines_removed"]) == (2, 4)


def test_maps_lines_and_learning_when_sensor_sent_reduced_write() -> None:
    def events(tool_input: dict[str, Any]) -> tuple[Event, ...]:
        hook = a_hook_input("PreToolUse", tool_name="Write", tool_input=tool_input)
        return ClaudeHookMapper().map(an_envelope(hook)).events

    inbox = "/work/demo-hub/brain/_inbox/note.md"
    plain = events({"file_path": f"{HOOK_CWD}/a.py", "content_lines": 4_000})
    headed = events({"file_path": inbox, "content_lines": 2, "content_heading": "Idea"})
    bare = events({"file_path": inbox, "content_lines": 2})

    assert [event.payload.get("lines_added") for event in plain] == [4_000]
    assert [event.payload.get("text") for event in headed] == [None, "Idea"]
    assert [event.payload.get("text") for event in bare] == [None, "note"]


def test_maps_output_size_when_sensor_sent_reduced_response() -> None:
    hook = a_hook_input("PostToolUse", tool_response=..., tool_response_bytes=123_456)

    event = _only(hook)

    assert event.payload["output_bytes"] == 123_456
