"""The agent-session routes over recording command ports (RT): what each route passes on, and
the RFC 9457 problem each core agent-session error becomes (types
``urn:agent-hub:problem:agent-session-<code>``). The use case behind them is tested in core."""

from typing import Any

import pytest

from agent_hub.core.agent_sessions.agent_session import (
    CreateAgentSession,
    PermissionDecision,
    SendMessage,
    SessionSettings,
)
from agent_hub.core.agent_sessions.errors import (
    AgentSessionNotFoundError,
    InvalidDecisionError,
    InvalidWorkdirError,
    LiveLimitError,
    LogFullError,
    MessageTooLargeError,
    PermissionAnsweredError,
    SessionBusyError,
    SessionsOffError,
    SessionsUnavailableError,
    SessionTerminalError,
    UnknownPermissionError,
    UnknownResumeError,
)
from agent_hub.core.testing.read_model_builders import AGENT_SESSION_ID, WORKDIR_ID

BASE = "/api/v1/agent-sessions"
ONE = f"{BASE}/{AGENT_SESSION_ID}"
PROBLEM = "urn:agent-hub:problem:agent-session-"
CREATE = {"project": "demo", "workdir_id": WORKDIR_ID}
SENTINEL = "sentinel-conversation-text-7f3a"


def _problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    document: dict[str, Any] = response.json()
    assert document["type"] == f"{PROBLEM}{code}"
    assert document["status"] == status
    assert document["instance"] == response.request.url.path
    return document


def test_passes_request_and_sets_location_when_create_called(agent_session_app: Any) -> None:
    body = CREATE | {"mode": "plan", "prompt": "Run the tests."}

    response = agent_session_app.client.post(BASE, json=body)

    assert response.status_code == 201, response.text
    assert response.headers["location"] == ONE
    assert agent_session_app.control.calls == [
        ("create", (CreateAgentSession.model_validate(body),))
    ]


def test_passes_text_in_order_when_send_called_twice(agent_session_app: Any) -> None:
    for text in ("first", "second"):
        response = agent_session_app.client.post(f"{ONE}/messages", json={"text": text})
        assert response.status_code == 202, response.text

    assert agent_session_app.control.calls == [
        ("send", (AGENT_SESSION_ID, SendMessage(text="first"))),
        ("send", (AGENT_SESSION_ID, SendMessage(text="second"))),
    ]


def test_passes_request_id_and_decision_when_permission_answer_posted(
    agent_session_app: Any,
) -> None:
    body = {"decision": "always", "suggestion": 0}

    response = agent_session_app.client.post(f"{ONE}/permissions/req-1", json=body)

    assert response.status_code == 200, response.text
    assert agent_session_app.control.calls == [
        ("answer", (AGENT_SESSION_ID, "req-1", PermissionDecision.model_validate(body)))
    ]


def test_passes_mode_when_settings_changed(agent_session_app: Any) -> None:
    response = agent_session_app.client.post(f"{ONE}/settings", json={"mode": "acceptEdits"})

    assert response.status_code == 200, response.text
    assert agent_session_app.control.calls == [
        ("change_settings", (AGENT_SESSION_ID, SessionSettings(mode="acceptEdits")))
    ]


def test_passes_after_and_limit_when_events_page_read(agent_session_app: Any) -> None:
    response = agent_session_app.client.get(f"{ONE}/events", params={"after": 3, "limit": 2})

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["seq"] == 4
    assert agent_session_app.control.calls == [("events", (AGENT_SESSION_ID, 3, 2))]


@pytest.mark.parametrize("limit", ["0", "501", "x"])
def test_refuses_limit_when_events_page_limit_out_of_range(
    agent_session_app: Any, limit: str
) -> None:
    response = agent_session_app.client.get(f"{ONE}/events", params={"limit": limit})

    assert response.status_code == 400, response.text
    assert agent_session_app.control.calls == []


def test_answers_204_without_body_when_delete_called(agent_session_app: Any) -> None:
    response = agent_session_app.client.delete(ONE)

    assert (response.status_code, response.content) == (204, b"")
    assert agent_session_app.control.calls == [("delete", (AGENT_SESSION_ID,))]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", ONE, None),
        ("delete", ONE, None),
        ("get", f"{ONE}/events", None),
        ("post", f"{ONE}/messages", {"text": "hi"}),
        ("post", f"{ONE}/interrupt", {}),
        ("post", f"{ONE}/settings", {"mode": "plan"}),
        ("post", f"{ONE}/close", {}),
    ],
)
def test_answers_404_problem_when_session_not_found(
    agent_session_app: Any, *, method: str, path: str, body: object
) -> None:
    port_method = {
        ONE: "snapshot" if method == "get" else "delete",
        f"{ONE}/events": "events",
        f"{ONE}/messages": "send",
        f"{ONE}/interrupt": "interrupt",
        f"{ONE}/settings": "change_settings",
        f"{ONE}/close": "close",
    }[path]
    agent_session_app.control.failures[port_method] = AgentSessionNotFoundError(AGENT_SESSION_ID)

    response = agent_session_app.client.request(
        method.upper(), path, json=body if body is not None else None
    )

    document = _problem(response, 404, "not-found")
    assert document["title"] == "Agent session not found"
    assert AGENT_SESSION_ID in document["detail"]


def test_answers_409_naming_resume_when_session_terminal(agent_session_app: Any) -> None:
    error = SessionTerminalError(AGENT_SESSION_ID, status="ended")
    agent_session_app.control.failures["send"] = error

    response = agent_session_app.client.post(f"{ONE}/messages", json={"text": SENTINEL})

    document = _problem(response, 409, "terminal")
    assert document["session_status"] == "ended"
    assert "resume" in document["detail"].lower()
    assert SENTINEL not in response.text


def test_answers_409_busy_when_send_after_interrupt_pending(agent_session_app: Any) -> None:
    agent_session_app.control.failures["send"] = SessionBusyError(AGENT_SESSION_ID)

    response = agent_session_app.client.post(f"{ONE}/messages", json={"text": SENTINEL})

    _problem(response, 409, "busy")
    assert SENTINEL not in response.text


def test_answers_429_naming_limit_when_concurrency_limit_reached(agent_session_app: Any) -> None:
    agent_session_app.control.failures["create"] = LiveLimitError(limit=2)

    response = agent_session_app.client.post(BASE, json=CREATE)

    document = _problem(response, 429, "limit")
    assert document["limit"] == 2
    assert "2" in document["detail"]


def test_answers_409_log_full_naming_resume_when_caps_reached(agent_session_app: Any) -> None:
    agent_session_app.control.failures["send"] = LogFullError(AGENT_SESSION_ID)

    response = agent_session_app.client.post(f"{ONE}/messages", json={"text": SENTINEL})

    document = _problem(response, 409, "log-full")
    assert "Resume" in document["detail"]
    assert SENTINEL not in response.text


def test_answers_conflict_when_permission_answer_repeated(agent_session_app: Any) -> None:
    agent_session_app.control.failures["answer"] = PermissionAnsweredError("req-1")

    response = agent_session_app.client.post(f"{ONE}/permissions/req-1", json={"decision": "allow"})

    document = _problem(response, 409, "answered")
    assert document["request_id"] == "req-1"


def test_answers_not_found_when_permission_answer_names_unknown_request(
    agent_session_app: Any,
) -> None:
    agent_session_app.control.failures["answer"] = UnknownPermissionError("req-9")

    response = agent_session_app.client.post(
        f"{ONE}/permissions/req-9", json={"decision": "deny", "message": SENTINEL}
    )

    document = _problem(response, 404, "unknown-request")
    assert document["request_id"] == "req-9"
    assert SENTINEL not in response.text


def test_answers_invalid_decision_when_permission_answer_does_not_fit_request(
    agent_session_app: Any,
) -> None:
    reason = "the suggestion is not a localSettings rule"
    agent_session_app.control.failures["answer"] = InvalidDecisionError(reason)

    response = agent_session_app.client.post(
        f"{ONE}/permissions/req-1", json={"decision": "always", "suggestion": 1}
    )

    document = _problem(response, 422, "invalid-decision")
    assert document["detail"] == f"Invalid permission answer: {reason}."


def test_answers_422_without_echo_when_workdir_unknown(agent_session_app: Any) -> None:
    agent_session_app.control.failures["create"] = InvalidWorkdirError(WORKDIR_ID)

    response = agent_session_app.client.post(BASE, json=CREATE)

    document = _problem(response, 422, "invalid-workdir")
    assert document["errors"] == [{"pointer": "/workdir_id", "message": document["detail"]}]
    assert WORKDIR_ID not in response.text


def test_answers_422_without_echo_when_resume_fork_id_unknown(agent_session_app: Any) -> None:
    resume = "0b6c2f3e-1d2a-4c5b-9e8f-7a6b5c4d3e2f"
    agent_session_app.control.failures["create"] = UnknownResumeError(resume)

    response = agent_session_app.client.post(
        BASE, json=CREATE | {"resume_session_id": resume, "fork": True}
    )

    document = _problem(response, 422, "unknown-resume")
    assert document["errors"][0]["pointer"] == "/resume_session_id"
    assert resume not in response.text


def test_answers_413_naming_limit_when_send_message_too_large(agent_session_app: Any) -> None:
    agent_session_app.control.failures["send"] = MessageTooLargeError(size=70_000, limit=65_536)

    response = agent_session_app.client.post(f"{ONE}/messages", json={"text": SENTINEL})

    document = _problem(response, 413, "message-too-large")
    assert (document["limit"], document["size"]) == (65_536, 70_000)
    assert SENTINEL not in response.text


def test_answers_503_naming_cause_when_unavailable(agent_session_app: Any) -> None:
    cause = "Install agent-hub[sessions] to drive sessions"
    agent_session_app.control.failures["create"] = SessionsUnavailableError(cause)

    response = agent_session_app.client.post(BASE, json=CREATE)

    document = _problem(response, 503, "unavailable")
    assert (document["reason"], document["detail"]) == (cause, cause)


def test_answers_off_problem_when_control_reports_sessions_off(agent_session_app: Any) -> None:
    agent_session_app.control.failures["capabilities"] = SessionsOffError()

    response = agent_session_app.client.get(f"{BASE}/capabilities")

    assert response.status_code == 404
    assert response.json()["type"] == "urn:agent-hub:problem:agent-sessions-off"
