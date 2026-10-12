"""Metadata only, end to end (AC-200.20, D10, D11): text a session or a run carries is never
stored or served, whichever entry point brings it in.

Body text (prompts, assistant text, thinking, tool output, Write content, Edit strings, run
output) carries ``BODY``; it must be dropped. Commands and error lines are kept short texts, so
they carry ``LEAK_SAMPLE`` instead, which redaction must replace. A failed tool's error text
carries ``ERROR_BODY``, which only its short ``error_message`` (300 characters) may keep (AC-201.8,
ADR 0023). Every stored row is scanned (each column as SQLite holds it) and every read endpoint's
answer is scanned too.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from agent_hub.cli.main import app as hub
from agent_hub.core.runner.run_record import Stage, picked_data, run_record
from agent_hub.core.testing.builders import an_event, events_to_jsonl
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.transcript_lines import (
    a_text_block,
    a_thinking_block,
    a_tool_result_line,
    a_tool_use_block,
    a_user_line,
    an_assistant_line,
    transcript_text,
)

BODY = "BODYSENTINEL-p7q9-content-never-stored"
ERROR_BODY = "ERRORSENTINEL-k3m5-only-in-error-message"
ERROR_MESSAGE_LIMIT = 300
# Synthetic, shaped like an Anthropic key so redaction replaces it; never a real secret.
LEAK_SAMPLE = "sk-ant-api03-SYNTHETICprivacySENTINEL0123456789"
HOOKS = "/api/v1/events/hooks"
REPO_FILE = "/work/demo-api/src/export.py"


def _tool(name: str, tool_input: dict[str, Any], tool_use_id: str) -> dict[str, Any]:
    return {"tool_name": name, "tool_input": tool_input, "tool_use_id": tool_use_id}


def _hook_inputs() -> list[dict[str, Any]]:
    write = _tool("Write", {"file_path": REPO_FILE, "content": f"x = '{BODY}'\n"}, "toolu_w")
    edit = _tool(
        "Edit",
        {"file_path": REPO_FILE, "old_string": BODY, "new_string": f"{BODY}!"},
        "toolu_e",
    )
    inbox = _tool(
        "Write",
        {"file_path": "/work/demo-hub/brain/_inbox/note.md", "content": f"# Title\n\n{BODY}\n"},
        "toolu_n",
    )
    bash = _tool("Bash", {"command": f"ANTHROPIC_API_KEY={LEAK_SAMPLE} make check"}, "toolu_b")
    return [
        a_hook_input("SessionStart"),
        a_hook_input("UserPromptSubmit", prompt=f"please {BODY}"),
        a_hook_input("PreToolUse", **write),
        a_hook_input("PreToolUse", **edit),
        a_hook_input("PreToolUse", **inbox),
        a_hook_input("PreToolUse", **bash),
        a_hook_input(
            "PostToolUse",
            **bash,
            tool_response={"stdout": BODY, "stderr": BODY, "interrupted": False},
        ),
        a_hook_input(
            "PostToolUseFailure",
            **write,
            error=f"failed with {LEAK_SAMPLE}\n{ERROR_BODY}",
            is_interrupt=False,
        ),
    ]


def _transcript_lines(session: str) -> list[dict[str, Any]]:
    write = a_tool_use_block("toolu_tw", "Write", {"file_path": REPO_FILE, "content": BODY})
    edit = a_tool_use_block(
        "toolu_te", "Edit", {"file_path": REPO_FILE, "old_string": BODY, "new_string": BODY}
    )
    lines = [
        a_user_line(f"prompt {BODY}"),
        an_assistant_line(
            [a_thinking_block(f"thinking {BODY}"), a_text_block(f"answer {BODY}"), write, edit],
            message_id=f"msg_{session}",
        ),
        a_tool_result_line("toolu_tw", content=f"output {BODY}"),
        a_tool_result_line(
            "toolu_te",
            content=[{"type": "text", "text": f"Exit 1 {LEAK_SAMPLE}\n{ERROR_BODY}"}],
            is_error=True,
        ),
    ]
    return [line | {"sessionId": session} for line in lines]


def _run_records() -> list[dict[str, Any]]:
    common: dict[str, Any] = {"run_id": "9c8d7e6f", "issue_id": "DEM-9", "repo": "demo-api"}
    return [
        run_record(
            ts="2026-10-11T09:00:00+00:00",
            state=Stage.PICKED,
            event="picked",
            live=True,
            data=picked_data(budget=5.0, max_turns=40, model="opus", transport="api"),
            **common,
        ),
        run_record(
            ts="2026-10-11T09:00:01+00:00",
            state=Stage.IMPLEMENTING,
            event="agent_finished",
            live=True,
            data={"cost_usd": 1.0, "turns": 3, "result": BODY, "output": BODY},
            **common,
        ),
        run_record(
            ts="2026-10-11T09:00:02+00:00",
            state=Stage.VERIFYING,
            event="failed",
            live=True,
            data={"stage": "verifying", "reason": f"gate failed: {LEAK_SAMPLE}", "log": BODY},
            **common,
        ),
    ]


def _collect(*args: str) -> None:
    result = CliRunner().invoke(hub, ["collect", *args])
    assert result.exit_code == 0, result.output


def _ingest_everything(composed: Any, tmp_path: Path) -> None:
    for hook in _hook_inputs():
        envelope = an_envelope(hook).model_dump(mode="json")
        assert composed.client.post(HOOKS, json=envelope).status_code == 202
    live = composed.projects / "-work-demo-api" / "session-1.jsonl"
    live.write_text(transcript_text(_transcript_lines("session-1")), encoding="utf-8")
    stop = an_envelope(a_hook_input("Stop", transcript_path=str(live)))
    assert composed.client.post(HOOKS, json=stop.model_dump(mode="json")).json()["appended"] > 0

    db = str(composed.settings.db_path)
    backfill = tmp_path / "session-2.jsonl"
    backfill.write_text(transcript_text(_transcript_lines("session-2")), encoding="utf-8")
    _collect("--transcript", str(backfill), "--project", "demo", "--db", db)
    runs = tmp_path / "runs.jsonl"
    runs.write_text("".join(json.dumps(r) + "\n" for r in _run_records()), encoding="utf-8")
    _collect("--runs", str(runs), "--project", "demo", "--db", db)
    canonical = tmp_path / "events.jsonl"
    command = f"curl -H 'x-api-key: {LEAK_SAMPLE}' https://example.org"
    # A JSON Lines file can name any payload key: keys outside "Payload kept" are dropped (D11).
    body_keys = {"tool_input": {"command": BODY}, "output": BODY, "prompt": BODY, "content": BODY}
    event = an_event(
        session="session-3",
        source_id="jsonl-bash",
        payload={"tool": "Bash", "command": command} | body_keys,
    )
    canonical.write_text(events_to_jsonl([event]), encoding="utf-8")
    _collect(str(canonical), "--db", db)


def _jsonl_payload(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        [(payload,)] = connection.execute(
            "SELECT payload FROM events WHERE source_id = 'jsonl-bash'"
        ).fetchall()
    loaded: dict[str, Any] = json.loads(payload)
    return loaded


def _is_problem(value: dict[str, Any]) -> bool:
    """A problem of ``/sessions/{id}/problems``: its ``message`` is the stored error message."""
    return {"kind", "resolution", "message"} <= set(value)


def _without_error_messages(value: Any) -> Any:
    """``value`` with every ``error_message`` key (and each problem's ``message``, which serves
    it) removed, at any depth."""
    if isinstance(value, dict):
        dropped = {"error_message", "message"} if _is_problem(value) else {"error_message"}
        return {k: _without_error_messages(v) for k, v in value.items() if k not in dropped}
    if isinstance(value, list):
        return [_without_error_messages(item) for item in value]
    return value


def _error_messages(value: Any) -> list[Any]:
    if isinstance(value, dict):
        found = [value["error_message"]] if "error_message" in value else []
        return found + [m for v in value.values() for m in _error_messages(v)]
    if isinstance(value, list):
        return [m for item in value for m in _error_messages(item)]
    return []


def _stored_payloads(db_path: Path) -> list[Any]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT payload FROM events").fetchall()
    return [json.loads(payload) for (payload,) in rows]


def _stored_text(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM events").fetchall()
    assert len(rows) > 20
    return "\n".join(repr(row) for row in rows)


def _paths(composed: Any) -> list[str]:
    get = composed.client.get
    sessions = [item["id"] for item in get("/api/v1/sessions?limit=200").json()["items"]]
    runs = [item["id"] for item in get("/api/v1/workflow-runs").json()["items"]]
    approvals = [item["id"] for item in get("/api/v1/approvals").json()["items"]]
    learnings = [item["id"] for item in get("/api/v1/learnings").json()["items"]]
    assert {"session-1", "session-2"} <= set(sessions)
    assert runs
    assert learnings
    paths = [
        "/api/v1/sessions?limit=200",
        "/api/v1/live-sessions",
        "/api/v1/workflow-runs",
        "/api/v1/approvals",
        "/api/v1/learnings",
        "/api/v1/needs-you",
        "/api/v1/activity",
        f"/api/v1/search?q={BODY}",
        "/api/v1/search?q=Bash",
        "/api/v1/collector/status",
        "/api/v1/settings",
    ]
    for session in sessions:
        base = f"/api/v1/sessions/{session}"
        paths += [base, f"{base}/summary", f"{base}/events?limit=200", f"{base}/files"]
        paths += [f"{base}/cost", f"{base}/problems"]
    paths += [f"/api/v1/workflow-runs/{run}" for run in runs]
    paths += [f"/api/v1/approvals/{approval}" for approval in approvals]
    paths += [f"/api/v1/learnings/{learning}" for learning in learnings]
    return paths


def test_stores_and_serves_no_body_or_secret_when_ingested_through_every_entry_point(
    composed: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _ingest_everything(composed, tmp_path)

    stored = _stored_text(composed.settings.db_path)
    assert BODY not in stored
    assert LEAK_SAMPLE not in stored
    payloads = _stored_payloads(composed.settings.db_path)
    assert ERROR_BODY not in json.dumps(_without_error_messages(payloads))
    messages = _error_messages(payloads)
    assert any(ERROR_BODY in message for message in messages)
    assert all(len(message) <= ERROR_MESSAGE_LIMIT for message in messages)
    assert "[redacted: anthropic key]" in stored
    assert _jsonl_payload(composed.settings.db_path) == {
        "tool": "Bash",
        "command": "curl -H 'x-api-key: [redacted: anthropic key]' https://example.org",
    }
    for path in _paths(composed):
        response = composed.client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert BODY not in response.text, path
        assert LEAK_SAMPLE not in response.text, path
        assert ERROR_BODY not in json.dumps(_without_error_messages(response.json())), path
    listed = composed.client.get("/api/v1/sessions?limit=200").json()["items"]
    served = [composed.client.get(f"/api/v1/sessions/{i['id']}/problems").json() for i in listed]
    messages = [p["message"] for body in served for p in body["items"]]
    assert any(ERROR_BODY in message for message in messages)
    assert all(len(message) <= ERROR_MESSAGE_LIMIT for message in messages)
