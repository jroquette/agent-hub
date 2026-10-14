"""The agent-session routes over recording command ports (RT): what each route passes on, and
the RFC 9457 problem each core agent-session error becomes (types
``urn:agent-hub:problem:agent-session-<code>``); then the same routes over the real use case
(``agent_session_app``, CP): AC-165.14-.35 as the API answers them."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.composition import build_app
from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.agent_sessions.agent_session import (
    CreateAgentSession,
    PermissionDecision,
    SendMessage,
    SessionSettings,
)
from agent_hub.core.agent_sessions.driver import (
    Allow,
    Deny,
    DriverCapabilities,
    PastSession,
    PermissionRequest,
    PermissionSuggestion,
    TextBlock,
    Thinking,
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
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.testing.agent_session_rig import HUB_PATH, START, WEB_URL
from agent_hub.core.testing.read_model_builders import AGENT_SESSION_ID, WORKDIR_ID
from agent_hub.core.testing.session_driver_fakes import Hold, InMemorySessionDriver

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


def test_passes_request_and_sets_location_when_create_called(recorded_app: Any) -> None:
    body = CREATE | {"mode": "plan", "prompt": "Run the tests."}

    response = recorded_app.client.post(BASE, json=body)

    assert response.status_code == 201, response.text
    assert response.headers["location"] == ONE
    assert recorded_app.control.calls == [("create", (CreateAgentSession.model_validate(body),))]


def test_passes_text_in_order_when_send_called_twice(recorded_app: Any) -> None:
    for text in ("first", "second"):
        response = recorded_app.client.post(f"{ONE}/messages", json={"text": text})
        assert response.status_code == 202, response.text

    assert recorded_app.control.calls == [
        ("send", (AGENT_SESSION_ID, SendMessage(text="first"))),
        ("send", (AGENT_SESSION_ID, SendMessage(text="second"))),
    ]


def test_passes_request_id_and_decision_when_permission_answer_posted(
    recorded_app: Any,
) -> None:
    body = {"decision": "always", "suggestion": 0}

    response = recorded_app.client.post(f"{ONE}/permissions/req-1", json=body)

    assert response.status_code == 200, response.text
    assert recorded_app.control.calls == [
        ("answer", (AGENT_SESSION_ID, "req-1", PermissionDecision.model_validate(body)))
    ]


def test_passes_mode_when_settings_changed(recorded_app: Any) -> None:
    response = recorded_app.client.post(f"{ONE}/settings", json={"mode": "acceptEdits"})

    assert response.status_code == 200, response.text
    assert recorded_app.control.calls == [
        ("change_settings", (AGENT_SESSION_ID, SessionSettings(mode="acceptEdits")))
    ]


def test_passes_after_and_limit_when_events_page_read(recorded_app: Any) -> None:
    response = recorded_app.client.get(f"{ONE}/events", params={"after": 3, "limit": 2})

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["seq"] == 4
    assert recorded_app.control.calls == [("events", (AGENT_SESSION_ID, 3, 2))]


@pytest.mark.parametrize("limit", ["0", "501", "x"])
def test_refuses_limit_when_events_page_limit_out_of_range(recorded_app: Any, limit: str) -> None:
    response = recorded_app.client.get(f"{ONE}/events", params={"limit": limit})

    assert response.status_code == 400, response.text
    assert recorded_app.control.calls == []


def test_answers_204_without_body_when_delete_called(recorded_app: Any) -> None:
    response = recorded_app.client.delete(ONE)

    assert (response.status_code, response.content) == (204, b"")
    assert recorded_app.control.calls == [("delete", (AGENT_SESSION_ID,))]


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
    recorded_app: Any, *, method: str, path: str, body: object
) -> None:
    port_method = {
        ONE: "snapshot" if method == "get" else "delete",
        f"{ONE}/events": "events",
        f"{ONE}/messages": "send",
        f"{ONE}/interrupt": "interrupt",
        f"{ONE}/settings": "change_settings",
        f"{ONE}/close": "close",
    }[path]
    recorded_app.control.failures[port_method] = AgentSessionNotFoundError(AGENT_SESSION_ID)

    response = recorded_app.client.request(
        method.upper(), path, json=body if body is not None else None
    )

    document = _problem(response, 404, "not-found")
    assert document["title"] == "Agent session not found"
    assert AGENT_SESSION_ID in document["detail"]


def test_answers_409_naming_resume_when_session_terminal(recorded_app: Any) -> None:
    error = SessionTerminalError(AGENT_SESSION_ID, status="ended")
    recorded_app.control.failures["send"] = error

    response = recorded_app.client.post(f"{ONE}/messages", json={"text": SENTINEL})

    document = _problem(response, 409, "terminal")
    assert document["session_status"] == "ended"
    assert "resume" in document["detail"].lower()
    assert SENTINEL not in response.text


def test_answers_409_busy_when_send_after_interrupt_pending(recorded_app: Any) -> None:
    recorded_app.control.failures["send"] = SessionBusyError(AGENT_SESSION_ID)

    response = recorded_app.client.post(f"{ONE}/messages", json={"text": SENTINEL})

    _problem(response, 409, "busy")
    assert SENTINEL not in response.text


def test_answers_429_naming_limit_when_concurrency_limit_reached(
    recorded_app: Any,
) -> None:
    recorded_app.control.failures["create"] = LiveLimitError(limit=2)

    response = recorded_app.client.post(BASE, json=CREATE)

    document = _problem(response, 429, "limit")
    assert document["limit"] == 2
    assert "2" in document["detail"]


def test_answers_409_log_full_naming_resume_when_caps_reached(recorded_app: Any) -> None:
    recorded_app.control.failures["send"] = LogFullError(AGENT_SESSION_ID)

    response = recorded_app.client.post(f"{ONE}/messages", json={"text": SENTINEL})

    document = _problem(response, 409, "log-full")
    assert "Resume" in document["detail"]
    assert SENTINEL not in response.text


def test_answers_conflict_when_permission_answer_repeated(recorded_app: Any) -> None:
    recorded_app.control.failures["answer"] = PermissionAnsweredError("req-1")

    response = recorded_app.client.post(f"{ONE}/permissions/req-1", json={"decision": "allow"})

    document = _problem(response, 409, "answered")
    assert document["request_id"] == "req-1"


def test_answers_not_found_when_permission_answer_names_unknown_request(
    recorded_app: Any,
) -> None:
    recorded_app.control.failures["answer"] = UnknownPermissionError("req-9")

    response = recorded_app.client.post(
        f"{ONE}/permissions/req-9", json={"decision": "deny", "message": SENTINEL}
    )

    document = _problem(response, 404, "unknown-request")
    assert document["request_id"] == "req-9"
    assert SENTINEL not in response.text


def test_answers_invalid_decision_when_permission_answer_does_not_fit_request(
    recorded_app: Any,
) -> None:
    reason = "the suggestion is not a localSettings rule"
    recorded_app.control.failures["answer"] = InvalidDecisionError(reason)

    response = recorded_app.client.post(
        f"{ONE}/permissions/req-1", json={"decision": "always", "suggestion": 1}
    )

    document = _problem(response, 422, "invalid-decision")
    assert document["detail"] == f"Invalid permission answer: {reason}."


def test_answers_422_without_echo_when_workdir_unknown(recorded_app: Any) -> None:
    recorded_app.control.failures["create"] = InvalidWorkdirError(WORKDIR_ID)

    response = recorded_app.client.post(BASE, json=CREATE)

    document = _problem(response, 422, "invalid-workdir")
    assert document["errors"] == [{"pointer": "/workdir_id", "message": document["detail"]}]
    assert WORKDIR_ID not in response.text


def test_answers_422_without_echo_when_resume_fork_id_unknown(recorded_app: Any) -> None:
    resume = "0b6c2f3e-1d2a-4c5b-9e8f-7a6b5c4d3e2f"
    recorded_app.control.failures["create"] = UnknownResumeError(resume)

    response = recorded_app.client.post(
        BASE, json=CREATE | {"resume_session_id": resume, "fork": True}
    )

    document = _problem(response, 422, "unknown-resume")
    assert document["errors"][0]["pointer"] == "/resume_session_id"
    assert resume not in response.text


def test_answers_413_naming_limit_when_send_message_too_large(recorded_app: Any) -> None:
    recorded_app.control.failures["send"] = MessageTooLargeError(size=70_000, limit=65_536)

    response = recorded_app.client.post(f"{ONE}/messages", json={"text": SENTINEL})

    document = _problem(response, 413, "message-too-large")
    assert (document["limit"], document["size"]) == (65_536, 70_000)
    assert SENTINEL not in response.text


def test_answers_503_naming_cause_when_unavailable(recorded_app: Any) -> None:
    cause = "Install agent-hub[sessions] to drive sessions"
    recorded_app.control.failures["create"] = SessionsUnavailableError(cause)

    response = recorded_app.client.post(BASE, json=CREATE)

    document = _problem(response, 503, "unavailable")
    assert (document["reason"], document["detail"]) == (cause, cause)


def test_answers_off_problem_when_control_reports_sessions_off(recorded_app: Any) -> None:
    recorded_app.control.failures["capabilities"] = SessionsOffError()

    response = recorded_app.client.get(f"{BASE}/capabilities")

    assert response.status_code == 404
    assert response.json()["type"] == "urn:agent-hub:problem:agent-sessions-off"


# The routes over the real AgentSessionControl (in-memory driver and store): AC-165.14-.35 at
# the API, one test per AC keyword.

ASK = PermissionRequest(
    request_id="req-1",
    tool="Bash",
    input={"command": f"echo {SENTINEL}"},
    suggestions=(
        PermissionSuggestion(index=0, destination="localSettings", rule={"tool": "Bash"}),
    ),
)
PAST = PastSession(
    session_id="11111111-2222-4333-8444-555555555555",
    title="Fix the flaky test",
    last_activity=START - timedelta(days=1),
    cwd=HUB_PATH,
)


def _created(app: Any, prompt: str | None = None, **fields: object) -> dict[str, Any]:
    body: dict[str, object] = dict(CREATE) | fields
    if prompt is not None:
        body["prompt"] = prompt
    response = app.client.post(BASE, json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    assert response.headers["location"].endswith(created["id"])
    return created


def _waiting(app: Any) -> str:
    session_id = str(_created(app, "Ask first.")["id"])
    app.until_status(session_id, "waiting_permission")
    return session_id


def _asking(request: PermissionRequest = ASK, **options: Any) -> dict[str, Any]:
    return {"replies": {"Ask first.": (request, TextBlock(block=0, text="done"))}} | options


def _decisions(app: Any, session_id: str) -> list[tuple[str | None, object]]:
    records = app.rig.records(session_id)
    return [(r.by, r.body.get("decision")) for r in records if r.kind == "permission.decision"]


def test_lists_hub_workdir_when_workdir_listed(agent_session_app: Any) -> None:
    response = agent_session_app.client.get(f"{BASE}/workdirs", params={"project": "demo"})

    assert response.status_code == 200
    assert [item["workdir_id"] for item in response.json()["items"]] == [WORKDIR_ID]
    assert HUB_PATH not in response.text


def test_answers_not_found_when_workdir_listed_for_unknown_project(
    agent_session_app: Any,
) -> None:
    response = agent_session_app.client.get(f"{BASE}/workdirs", params={"project": "other"})

    assert response.status_code == 404


def test_refuses_unlisted_workdir_when_create_names_it(agent_session_app: Any) -> None:
    response = agent_session_app.client.post(BASE, json=CREATE | {"workdir_id": "f" * 16})

    _problem(response, 422, "invalid-workdir")
    assert all(call.method != "start" for call in agent_session_app.driver.calls)


def test_starts_idle_without_init_when_create_has_no_prompt(
    agent_session_app: Any,
) -> None:
    created = _created(agent_session_app)

    assert created["status"] == "idle"
    assert agent_session_app.kinds(created["id"]) == []
    start = next(call for call in agent_session_app.driver.calls if call.method == "start")
    spec = start.args[0]
    assert spec.cwd == HUB_PATH
    assert dict(spec.environment_extra) == {"AGENT_HUB_WEB_URL": WEB_URL}


def test_runs_first_turn_when_create_has_prompt(agent_session_app: Any) -> None:
    created = _created(agent_session_app, "Run the tests.")

    idle = agent_session_app.until_status(created["id"], "idle")

    assert created["status"] == "running"
    assert agent_session_app.kinds(created["id"]) == ["user.message", "init", "text", "result"]
    assert idle["claude_session_id"] is not None
    assert idle["cost_usd"] is not None


def test_logs_messages_in_order_when_send_called_during_turn(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(
        replies={"Work slowly.": (Hold(), TextBlock(block=0, text="done"))}
    )
    session_id = _created(app, "Work slowly.")["id"]

    response = app.client.post(f"{BASE}/{session_id}/messages", json={"text": "And then."})
    app.run(app.driver.release, app.rig.handle())
    app.until_status(session_id, "idle")
    deadline = time.monotonic() + 5
    while app.kinds(session_id).count("result") < 2 and time.monotonic() < deadline:
        time.sleep(0.005)

    assert response.status_code == 202, response.text
    assert response.json()["seq"] == 3
    sent = [call.args[0] for call in app.driver.calls if call.method == "send"]
    assert sent == ["Work slowly.", "And then."]


def test_refuses_message_too_large_when_send_over_limit(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(limits=SessionLimits(message_max_bytes=1024))
    session_id = _created(app)["id"]

    response = app.client.post(f"{BASE}/{session_id}/messages", json={"text": "x" * 2000})

    _problem(response, 413, "message-too-large")
    assert all(call.method != "send" for call in app.driver.calls)


def test_aborts_turn_when_interrupt_posted(open_agent_session_app: Any) -> None:
    app = open_agent_session_app(replies={"Long job.": (Hold(), TextBlock(block=0, text="x"))})
    session_id = _created(app, "Long job.")["id"]
    app.until_status(session_id, "running")

    response = app.client.post(f"{BASE}/{session_id}/interrupt", json={})
    idle = app.until_status(session_id, "idle")

    assert response.status_code == 202, response.text
    assert "interrupt" in app.kinds(session_id)
    assert idle["status"] == "idle"
    assert any(call.method == "interrupt" for call in app.driver.calls)


def test_changes_mode_and_model_when_settings_posted(agent_session_app: Any) -> None:
    session_id = _created(agent_session_app)["id"]

    mode = agent_session_app.client.post(
        f"{BASE}/{session_id}/settings", json={"mode": "acceptEdits"}
    )
    model = agent_session_app.client.post(f"{BASE}/{session_id}/settings", json={"model": "opus"})

    assert (mode.status_code, model.status_code) == (200, 200)
    assert (model.json()["mode"], model.json()["model"]) == ("acceptEdits", "opus")
    methods = [call.method for call in agent_session_app.driver.calls]
    assert methods[-2:] == ["set_mode", "set_model"]
    assert agent_session_app.kinds(session_id) == ["settings", "settings"]


def test_refuses_model_without_driver_call_when_settings_model_invalid(
    agent_session_app: Any,
) -> None:
    session_id = _created(agent_session_app)["id"]

    response = agent_session_app.client.post(
        f"{BASE}/{session_id}/settings", json={"model": "opus; rm -rf"}
    )

    assert response.status_code == 422
    assert all(call.method != "set_model" for call in agent_session_app.driver.calls)


def test_resumes_and_forks_listed_session_when_resume_fork_given(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(past_sessions=(PAST,))

    listed = app.client.get(f"{BASE}/resumable", params=CREATE)
    resumed = _created(app, resume_session_id=PAST.session_id)
    forked = _created(app, resume_session_id=PAST.session_id, fork=True)
    unknown = app.client.post(
        BASE, json=CREATE | {"resume_session_id": "9" * 8 + PAST.session_id[8:]}
    )

    assert [item["session_id"] for item in listed.json()["items"]] == [PAST.session_id]
    assert resumed["claude_session_id"] == PAST.session_id
    assert forked["claude_session_id"] != PAST.session_id
    specs = [call.args[0] for call in app.driver.calls if call.method == "start"]
    assert [(spec.resume, spec.fork) for spec in specs] == [
        (PAST.session_id, False),
        (PAST.session_id, True),
    ]
    _problem(unknown, 422, "unknown-resume")


def test_refuses_create_naming_limit_when_concurrency_limit_reached(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(limits=SessionLimits(sessions_max=2))
    first, _second = _created(app), _created(app)

    refused = app.client.post(BASE, json=CREATE)
    app.client.post(f"{BASE}/{first['id']}/close", json={})
    third = app.client.post(BASE, json=CREATE)

    document = _problem(refused, 429, "limit")
    assert document["limit"] == 2
    assert third.status_code == 201


def test_ends_session_when_idle_timeout_passes(open_agent_session_app: Any) -> None:
    app = open_agent_session_app(limits=SessionLimits(idle_seconds=60))
    session_id = _created(app, "Run the tests.")["id"]
    app.until_status(session_id, "idle")

    app.sweep(30)
    still = app.get(session_id)
    app.sweep(31)
    ended = app.until_status(session_id, "ended")

    assert still["status"] == "idle"
    assert ended["end_reason"] == "idle_timeout"
    refused = app.client.post(f"{BASE}/{session_id}/messages", json={"text": "More?"})
    _problem(refused, 409, "terminal")


def test_marks_session_failed_when_driver_exits_non_zero(agent_session_app: Any) -> None:
    session_id = _created(agent_session_app)["id"]

    agent_session_app.run(agent_session_app.driver.fail_with, agent_session_app.rig.handle(), 3)
    failed = agent_session_app.until_status(session_id, "failed")

    assert failed["end_reason"] == "failed"
    assert agent_session_app.kinds(session_id) == ["error", "exited"]
    assert _created(agent_session_app)["status"] == "idle"


def test_shows_open_request_raw_and_stores_redacted_when_permission_request_arrives(
    open_agent_session_app: Any,
) -> None:
    token = "ghp_" + "Ab1" * 12
    request = ASK.model_copy(update={"input": {"command": f"curl -H 'token: {token}' x.test"}})
    app = open_agent_session_app(**_asking(request))
    session_id = _waiting(app)

    snapshot = app.get(session_id)
    events = app.client.get(f"{BASE}/{session_id}/events")

    open_permission = snapshot["open_permission"]
    assert open_permission["request_id"] == "req-1"
    assert token in open_permission["summary"]
    assert open_permission["deadline_at"] is not None
    assert token not in events.text
    assert "permission.request" in [item["kind"] for item in events.json()["items"]]


def test_allows_once_then_refuses_repeat_when_permission_answer_posted(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(**_asking())
    session_id = _waiting(app)
    answer = f"{BASE}/{session_id}/permissions/req-1"

    allowed = app.client.post(answer, json={"decision": "allow"})
    repeated = app.client.post(answer, json={"decision": "deny"})
    unknown = app.client.post(f"{BASE}/{session_id}/permissions/req-9", json={"decision": "allow"})
    app.until_status(session_id, "idle")

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["open_permission"] is None
    assert app.driver.answers == {"req-1": Allow()}
    _problem(repeated, 409, "answered")
    _problem(unknown, 404, "unknown-request")
    assert _decisions(app, session_id) == [("web", "allow")]


def test_refuses_always_without_suggestion_when_permission_answer_invalid(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(**_asking())
    session_id = _waiting(app)

    response = app.client.post(
        f"{BASE}/{session_id}/permissions/req-1", json={"decision": "always", "suggestion": 4}
    )

    _problem(response, 422, "invalid-decision")
    assert app.driver.answers == {}


def test_denies_by_timeout_when_permission_timeout_passes(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(**_asking(limits=SessionLimits(permission_timeout_seconds=60)))
    session_id = _waiting(app)

    app.sweep(30)
    still = app.get(session_id)
    app.sweep(30)
    app.until_status(session_id, "idle")

    assert still["open_permission"] is not None
    assert isinstance(app.driver.answers["req-1"], Deny)
    assert _decisions(app, session_id) == [("timeout", "deny")]


def test_passes_answers_when_ask_user_question_answered(
    open_agent_session_app: Any,
) -> None:
    question = PermissionRequest(
        request_id="req-q",
        tool="AskUserQuestion",
        input={"questions": [{"question": "Which runner?"}]},
        request_kind="ask_user_question",
    )
    app = open_agent_session_app(**_asking(question))
    session_id = _waiting(app)

    response = app.client.post(
        f"{BASE}/{session_id}/permissions/req-q",
        json={"decision": "allow", "answers": {"Which runner?": "pytest"}},
    )

    assert response.status_code == 200, response.text
    assert app.driver.answers["req-q"] == Allow(
        updated_input=question.input | {"answers": {"Which runner?": "pytest"}}
    )


def test_allows_then_sets_mode_when_plan_approval_answered(
    open_agent_session_app: Any,
) -> None:
    plan = PermissionRequest(
        request_id="req-p",
        tool="ExitPlanMode",
        input={"plan": "1. Fix the test"},
        request_kind="plan_approval",
    )
    app = open_agent_session_app(**_asking(plan))
    session_id = _waiting(app)

    response = app.client.post(
        f"{BASE}/{session_id}/permissions/req-p",
        json={"decision": "allow", "mode": "acceptEdits"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "acceptEdits"
    methods = [call.method for call in app.driver.calls]
    assert methods.index("answer_permission") < methods.index("set_mode")
    kinds = app.kinds(session_id)
    assert kinds.index("permission.decision") + 1 == kinds.index("settings")


def test_logs_every_command_by_web_when_audit_read(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(**_asking())
    session_id = _waiting(app)
    app.client.post(f"{BASE}/{session_id}/permissions/req-1", json={"decision": "allow"})
    app.until_status(session_id, "idle")
    app.client.post(f"{BASE}/{session_id}/settings", json={"mode": "plan"})
    app.client.post(f"{BASE}/{session_id}/close", json={})

    items = app.client.get(f"{BASE}/{session_id}/events").json()["items"]

    by_web = [(item["kind"], item["by"]) for item in items if item["by"] == "web"]
    assert by_web == [
        ("user.message", "web"),
        ("permission.decision", "web"),
        ("settings", "web"),
        ("close", "web"),
    ]
    assert [item["seq"] for item in items] == list(range(1, len(items) + 1))


def test_pages_persisted_log_when_events_page_read(agent_session_app: Any) -> None:
    session_id = _created(agent_session_app, "Run the tests.")["id"]
    agent_session_app.until_status(session_id, "idle")
    events = f"{BASE}/{session_id}/events"

    first = agent_session_app.client.get(events, params={"limit": 2}).json()
    rest = agent_session_app.client.get(
        events, params={"after": first["next_after"], "limit": 10}
    ).json()

    assert [item["seq"] for item in first["items"]] == [1, 2]
    assert first["next_after"] == 2
    assert [item["seq"] for item in rest["items"]] == [3, 4]
    assert rest["next_after"] is None


def test_ends_log_full_and_names_resume_when_caps_reached(
    open_agent_session_app: Any,
) -> None:
    turn = tuple(Thinking(text=f"step {number}") for number in range(120))
    limits = SessionLimits(log_records=100, log_bytes=64 * 1024, headroom=16)
    app = open_agent_session_app(replies={"Think a lot.": turn}, limits=limits)
    session_id = _created(app, "Think a lot.")["id"]

    ended = app.until_status(session_id, "ended")
    refused = app.client.post(f"{BASE}/{session_id}/messages", json={"text": "More?"})

    assert ended["end_reason"] == "log_full"
    assert "log.truncated" in app.kinds(session_id)
    document = _problem(refused, 409, "log-full")
    assert "Resume" in document["detail"]


def test_deletes_ended_session_and_refuses_live_one_when_delete_called(
    agent_session_app: Any,
) -> None:
    live = _created(agent_session_app)["id"]
    ended = _created(agent_session_app, "Run the tests.")["id"]
    agent_session_app.until_status(ended, "idle")
    agent_session_app.client.post(f"{BASE}/{ended}/close", json={})

    refused = agent_session_app.client.delete(f"{BASE}/{live}")
    deleted = agent_session_app.client.delete(f"{BASE}/{ended}")

    _problem(refused, 409, "busy")
    assert deleted.status_code == 204
    assert agent_session_app.client.get(f"{BASE}/{ended}").status_code == 404
    assert agent_session_app.client.get(f"{BASE}/{ended}/events").status_code == 404


def test_answers_cause_and_refuses_writes_when_unavailable(
    open_agent_session_app: Any,
) -> None:
    cause = "Install agent-hub[sessions] to drive sessions"
    driver = InMemorySessionDriver(capabilities=DriverCapabilities(available=False, reason=cause))
    app = open_agent_session_app(driver=driver)

    capabilities = app.client.get(f"{BASE}/capabilities")
    refused = app.client.post(BASE, json=CREATE)

    assert capabilities.status_code == 200
    assert (capabilities.json()["available"], capabilities.json()["reason"]) == (False, cause)
    assert _problem(refused, 503, "unavailable")["reason"] == cause
    assert all(call.method != "start" for call in driver.calls)


# The composed app (``build_app``) on a real SQLite file, a registered hub and the in-memory
# driver: workdirs from the registry, the children's URL, and a restart.

TOKEN = "t" * 43


@contextmanager
def _composed(settings: ApiSettings, projects_root: Path, web_dist: Path) -> Iterator[TestClient]:
    app = build_app(
        settings,
        projects_root=projects_root,
        web_dist=web_dist,
        session_driver=InMemorySessionDriver(),
        environ={},
    )
    origin = f"http://127.0.0.1:{settings.port}"
    with TestClient(
        app, base_url=origin, headers={"Origin": origin}, raise_server_exceptions=False
    ) as client:
        client.cookies.set(cookie_name(settings.port), TOKEN)
        yield client


def _until(client: TestClient, session_id: str, status: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while True:
        body: dict[str, Any] = client.get(f"{BASE}/{session_id}").json()
        if body["status"] == status or time.monotonic() > deadline:
            assert body["status"] == status, body
            return body
        time.sleep(0.005)


def test_keeps_log_and_ends_session_when_restart_opens_same_database(
    composed_settings: ApiSettings,
    *,
    projects_root: Path,
    web_dist: Path,
    make_hub: Any,
) -> None:
    hub = make_hub()
    settings = replace(composed_settings, session_token=TOKEN, clock=lambda: START)
    with _composed(settings, projects_root, web_dist) as first:
        assert (
            first.post(
                "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
            ).status_code
            == 201
        )
        workdirs = first.get(f"{BASE}/workdirs", params={"project": "demo"}).json()["items"]
        created = first.post(
            BASE,
            json={"project": "demo", "workdir_id": workdirs[0]["workdir_id"], "prompt": "Go."},
        ).json()
        _until(first, created["id"], "idle")
        before = first.get(f"{BASE}/{created['id']}/events").json()["items"]

    with _composed(settings, projects_root, web_dist) as second:
        after = second.get(f"{BASE}/{created['id']}").json()
        replayed = second.get(f"{BASE}/{created['id']}/events").json()["items"]

    assert workdirs[0]["kind"] == "hub"
    assert (after["status"], after["end_reason"]) == ("ended", "server_stopped")
    assert replayed[: len(before)] == before
    assert [item["kind"] for item in replayed][-1] == "exited"
