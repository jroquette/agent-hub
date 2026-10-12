"""``/sessions/{session_id}/problems`` and the problem counts of ``/sessions`` and
``/live-sessions`` on the composed app (AC-201.13): each problem says what, where, when, which
actor and whether it was handled; the summary is 1 to 5 deterministic lines, each naming an
event."""

from datetime import timedelta
from typing import Any

from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.session_scenarios import a_session_events

HOOKS = "/api/v1/events/hooks"
MAX_SUMMARY_LINES = 5
# Synthetic, shaped like an Anthropic key so redaction replaces it; never a real secret.
LEAK_SAMPLE = "sk-ant-api03-SYNTHETICproblemsSENTINEL0123456789"


def _failing_session(composed: Any) -> None:
    start = composed.settings.clock() - timedelta(minutes=30)
    tools = (
        ("Bash", {"command": "make check"}),
        ("Bash", {"command": "make check"}),
        ("Edit", {"path": "src/app.py"}),
        ("Read", {"path": "src/app.py"}),
        ("Bash", {"command": "make lint"}),
    )
    failed = frozenset({0, 2, 4})
    composed.store.append(
        a_session_events("session-1", start=start, tools=tools, failed_tools=failed)
    )


def test_returns_problems_and_summary_when_session_has_failures(composed: Any) -> None:
    _failing_session(composed)

    response = composed.client.get("/api/v1/sessions/session-1/problems")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "session-1"
    items = body["items"]
    assert [(p["kind"], p["tool"], p["where"], p["resolution"]) for p in items] == [
        ("command_exit", "Bash", "make check", "recovered"),
        ("tool_failed", "Edit", "src/app.py", "agent_continued"),
        ("command_exit", "Bash", "make lint", "needs_you"),
    ]
    assert all(p["message"] == "exit status 2" for p in items)
    assert all(p["actor"]["kind"] == "main" and p["derived"] for p in items)
    assert [p["at"] for p in items] == sorted(p["at"] for p in items)
    assert items[0]["resolved_by_event_id"] is not None
    assert items[2]["resolved_by_event_id"] is None
    summary = body["summary"]
    assert 1 <= len(summary) <= MAX_SUMMARY_LINES
    assert summary[0]["text"] == "3 problems: 1 needs you, 2 handled by the agent"
    assert {line["event_id"] for line in summary} <= {p["event_id"] for p in items}
    events = composed.client.get("/api/v1/sessions/session-1/events?limit=200").json()["items"]
    assert {p["event_id"] for p in items} <= {event["event_id"] for event in events}
    assert composed.client.get("/api/v1/sessions/session-1/problems").json() == body


def test_counts_problems_when_sessions_listed(composed: Any) -> None:
    _failing_session(composed)
    composed.store.append(a_session_events("session-2"))

    listed = composed.client.get("/api/v1/sessions").json()["items"]
    one = composed.client.get("/api/v1/sessions/session-1").json()

    counts = {item["id"]: item["problems"] for item in listed}
    expected = {"needs_you": 1, "open": 0, "handled": 2, "by_you": 0}
    assert counts == {
        "session-1": expected,
        "session-2": {"needs_you": 0, "open": 0, "handled": 0, "by_you": 0},
    }
    assert one["problems"] == expected


def _post(composed: Any, event_name: str, sent_at: str, **fields: Any) -> None:
    envelope = an_envelope(a_hook_input(event_name, **fields), sent_at=sent_at)
    response = composed.client.post(HOOKS, json=envelope.model_dump(mode="json"))
    assert response.status_code == 202, response.text


def test_names_needs_you_problem_when_live_session_waits_after_failure(composed: Any) -> None:
    bash = {"tool_name": "Bash", "tool_input": {"command": "make e2e"}, "tool_use_id": "toolu_e2e"}
    error = f"Exit code 2\nexport TOKEN={LEAK_SAMPLE}\n" + "detail " * 100
    _post(composed, "SessionStart", "2026-10-11T11:55:00.000Z")
    _post(composed, "PreToolUse", "2026-10-11T11:56:00.000Z", **bash)
    _post(composed, "PostToolUseFailure", "2026-10-11T11:57:00.000Z", **bash, error=error)

    working = composed.client.get("/api/v1/live-sessions").json()["items"]
    _post(composed, "Notification", "2026-10-11T11:58:00.000Z")
    waiting = composed.client.get("/api/v1/live-sessions").json()["items"]
    problems = composed.client.get("/api/v1/sessions/session-1/problems")

    (tile_working,) = working
    assert tile_working["problems"]["open"] == 1
    assert tile_working["needs_you_problem"] is None
    (tile,) = waiting
    assert tile["status"] == "waiting"
    assert tile["problems"]["needs_you"] == 1
    (problem,) = problems.json()["items"]
    assert (problem["kind"], problem["where"], problem["resolution"]) == (
        "command_exit",
        "make e2e",
        "needs_you",
    )
    assert tile["needs_you_problem"] == "Needs you: command_exit in make e2e"
    assert problem["message"].startswith("Exit code 2")
    assert "[redacted: anthropic key]" in problem["message"]
    assert len(problem["message"]) <= 300
    assert LEAK_SAMPLE not in problems.text + str(waiting)


def test_returns_empty_problems_when_session_clean(composed: Any) -> None:
    composed.store.append(a_session_events("session-2"))

    response = composed.client.get("/api/v1/sessions/session-2/problems")

    assert response.status_code == 200, response.text
    assert (response.json()["summary"], response.json()["items"]) == ([], [])


def test_answers_not_found_when_problems_session_unknown(composed: Any) -> None:
    response = composed.client.get("/api/v1/sessions/nope/problems")

    assert response.status_code == 404
    assert response.json()["title"] == "Session not found"
