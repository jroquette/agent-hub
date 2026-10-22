from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from agent_hub.api.app import create_app
from agent_hub.api.local_security import (
    AGENT_SESSION_CREATE_BODY_BYTES,
    AGENT_SESSION_MESSAGE_BODY_BYTES,
    CONTENT_SECURITY_POLICY,
    WEBSOCKET_POLICY_VIOLATION,
    LocalSecurityMiddleware,
    allowed_hosts,
    allowed_origins,
    is_hub_registry_write,
    is_item_write,
    is_json_media_type,
    is_run_write,
    is_strict_write,
    parse_allowed_hosts,
)
from agent_hub.api.settings import ApiSettings
from agent_hub.core.ingestion.hook_envelope import MAX_BODY_BYTES


def test_allows_loopback_names_with_port_when_hosts_listed() -> None:
    assert allowed_hosts(7420) == {"127.0.0.1:7420", "localhost:7420", "[::1]:7420"}


def test_allows_http_origins_of_hosts_when_origins_listed() -> None:
    assert allowed_origins(8001) == {
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://[::1]:8001",
    }


@pytest.mark.parametrize("directive", ["script-src", "style-src", "font-src", "connect-src"])
def test_limits_directive_to_self_when_policy_built(directive: str) -> None:
    assert f"{directive} 'self'" in CONTENT_SECURITY_POLICY.split("; ")


@pytest.mark.parametrize(
    "host", ["attacker.example", "127.0.0.1", "127.0.0.1:7421", "localhost.attacker.example:7420"]
)
def test_answers_forbidden_problem_when_host_not_loopback_at_port(client: Any, host: str) -> None:
    response = client.get("/api/v1/openapi.json", headers={"Host": host})

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Forbidden host"


@pytest.mark.parametrize("host", ["127.0.0.1:7420", "localhost:7420", "[::1]:7420"])
def test_serves_request_when_host_is_loopback_at_port(client: Any, host: str) -> None:
    response = client.get("/api/v1/openapi.json", headers={"Host": host})

    assert response.status_code == 200


def test_adds_extra_hosts_when_names_given() -> None:
    hosts = allowed_hosts(7420, extra=frozenset({"agent-hub.internal:7420", "127.0.0.1:8000"}))

    assert hosts == {
        "127.0.0.1:7420",
        "localhost:7420",
        "[::1]:7420",
        "agent-hub.internal:7420",
        "127.0.0.1:8000",
    }
    assert "http://127.0.0.1:8000" in allowed_origins(7420, extra=hosts)


def test_reads_names_with_server_port_when_port_omitted() -> None:
    parsed = parse_allowed_hosts(" Agent-Hub.internal , 127.0.0.1:8000,,[::1]:9000 ", port=7420)

    assert parsed == {"agent-hub.internal:7420", "127.0.0.1:8000", "[::1]:9000"}


def test_reads_nothing_when_value_empty() -> None:
    assert parse_allowed_hosts("", port=7420) == frozenset()


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "*.example.org",
        "host:*",
        "http://host:7420",
        "host/path",
        "host:0",
        "host:65536",
        "host:port",
        "user@host",
        "-host",
        "[::1",
    ],
)
def test_refuses_entry_when_not_plain_host_and_port(value: str) -> None:
    with pytest.raises(ValueError, match="AGENT_HUB_ALLOWED_HOSTS"):
        parse_allowed_hosts(value, port=7420)


def test_serves_request_when_host_added_by_settings(tmp_path: Path, web_dist: Path) -> None:
    settings = ApiSettings(
        db_path=tmp_path / "a.db",
        registry_path=tmp_path / "hubs.json",
        port=7420,
        running_version="0.9.0",
        allowed_hosts=frozenset({"127.0.0.1:8000"}),
    )
    with TestClient(
        create_app(settings, web_dist=web_dist), base_url="http://127.0.0.1:8000"
    ) as client:
        served = client.get("/api/v1/openapi.json")
        written = client.post("/api/v1/hubs", json={}, headers={"Origin": "http://127.0.0.1:8000"})
        foreign = client.get("/api/v1/openapi.json", headers={"Host": "127.0.0.1:8001"})

    assert served.status_code == 200
    assert written.status_code != 403
    assert foreign.status_code == 403


@pytest.mark.parametrize(
    "path", ["/api/v1/learnings/learning-1/accept", "/api/v1/learnings/a.b-c/reject"]
)
def test_marks_strict_write_when_post_to_learning_action(path: str) -> None:
    assert is_strict_write("POST", path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/learnings/learning-1/accept"),
        ("POST", "/api/v1/hubs"),
        ("POST", "/api/v1/events/hooks"),
        ("DELETE", "/api/v1/hubs/hub-1"),
        ("POST", "/api/v1/learnings/learning-1/archive"),
        ("POST", "/api/v1/learnings/a/b/accept"),
        ("POST", "/api/v1/learnings//accept"),
        ("POST", "/api/v1/learnings/learning-1/accept/extra"),
    ],
)
def test_keeps_default_checks_when_not_learning_action(method: str, path: str) -> None:
    assert not is_strict_write(method, path)


@pytest.mark.parametrize(
    "value",
    [
        "application/json",
        "APPLICATION/JSON",
        "application/json; charset=utf-8",
        " application/json ;q",
    ],
)
def test_reads_json_when_media_type_is_application_json(value: str) -> None:
    assert is_json_media_type(value)


@pytest.mark.parametrize(
    "value",
    [None, "", "text/plain", "application/jsonx", "application/merge-patch+json", "text/json"],
)
def test_refuses_json_when_media_type_is_other(value: str | None) -> None:
    assert not is_json_media_type(value)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/v1/events/stream",
        "/api/v1/agent-sessions/01929a4e-7a11-7c00-8a00-00000000a001/stream",
    ],
)
def test_closes_websocket_when_any_path_upgraded(client: TestClient, path: str) -> None:
    with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect(path):
        pass

    assert closed.value.code == WEBSOCKET_POLICY_VIOLATION


@pytest.mark.parametrize(
    ("method", "path"), [("POST", "/api/v1/hubs"), ("DELETE", "/api/v1/hubs/hub-1")]
)
def test_refuses_hub_registry_write_when_origin_missing(
    client: TestClient, method: str, path: str
) -> None:
    client.headers.pop("Origin", None)

    response = client.request(method, path, json={"path": "/home/demo/demo-hub"})

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden origin"


@pytest.mark.parametrize(
    "origin", ["http://localhost:7420", "http://127.0.0.1:7421", "null", "http://127.0.0.1"]
)
def test_refuses_hub_registration_when_origin_not_exactly_this_server(
    client: TestClient, origin: str
) -> None:
    response = client.post(
        "/api/v1/hubs", json={"path": "/home/demo/demo-hub"}, headers={"Origin": origin}
    )

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden origin"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/hubs"),
        ("DELETE", "/api/v1/hubs/hub-1"),
        ("DELETE", "/api/v1/hubs/a/b"),
        ("POST", "/api/v1/hubsx"),
        ("GET", "/api/v1/hubs"),
    ],
)
def test_marks_hub_registry_write_when_post_or_delete_on_hubs(method: str, path: str) -> None:
    expected = (method, path) in {("POST", "/api/v1/hubs"), ("DELETE", "/api/v1/hubs/hub-1")}

    assert is_hub_registry_write(method, path) is expected


RUN_WRITES = (
    "/api/v1/workflow-runs",
    "/api/v1/workflow-runs/run-1/cancel",
    "/api/v1/workflow-runs/run-1/resume",
    "/api/v1/workflow-runs/run-1/abandon",
    "/api/v1/approvals/run-1:ok:1/decision",
    # two-level-flows AC-2.14 (AGH-405): the owner answers a lost run's change request.
    "/api/v1/features/demo/demo-feature/change-requests/2/decision",
    # AGH-350 plan T12: the scenario writes run the CLI, the tracker or write into the hub.
    "/api/v1/scenarios/demo/order-walk/plan",
    "/api/v1/scenarios/demo/order-walk/runs",
    "/api/v1/scenario-runs/walk-1/investigation",
    "/api/v1/scenario-runs/walk-1/answer",
    "/api/v1/scenario-runs/walk-1/findings/f1/issue",
    "/api/v1/scenario-runs/walk-1/findings/f1/inbox",
)
OWN_JSON = {"Origin": "http://127.0.0.1:7420", "Content-Type": "application/json"}


@pytest.mark.parametrize("path", RUN_WRITES)
def test_marks_strict_run_write_when_post_to_run_command(path: str) -> None:
    assert is_strict_write("POST", path)
    assert is_run_write("POST", path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/workflow-runs"),
        ("GET", "/api/v1/workflow-runs/run-1"),
        ("POST", "/api/v1/workflow-runs/run-1/stream"),
        ("POST", "/api/v1/workflow-runs/a/b/cancel"),
        ("POST", "/api/v1/workflow-runs/run-1/cancel/extra"),
        ("GET", "/api/v1/approvals/run-1:ok:1/gate"),
        ("POST", "/api/v1/approvals/a/b/decision"),
        ("POST", "/api/v1/approvals/run-1:ok:1/decision/extra"),
        ("GET", "/api/v1/features/demo/demo-feature/change-requests/2/decision"),
        ("POST", "/api/v1/features/demo/demo-feature/change-requests/2/decision/extra"),
        ("GET", "/api/v1/scenarios"),
        ("GET", "/api/v1/scenario-runs/walk-1"),
        ("POST", "/api/v1/scenarios/demo/order-walk/plan/extra"),
        ("POST", "/api/v1/scenario-runs/walk-1/findings/f1/other"),
    ],
)
def test_keeps_default_checks_when_not_run_command(method: str, path: str) -> None:
    assert not is_run_write(method, path)
    assert not is_strict_write(method, path)


@pytest.mark.parametrize("path", RUN_WRITES)
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Content-Type": "application/json"}, 403),
        ({**OWN_JSON, "Origin": "http://127.0.0.1:7421"}, 403),
        ({**OWN_JSON, "Sec-Fetch-Site": "same-site"}, 403),
        ({**OWN_JSON, "Content-Type": "text/plain"}, 415),
        (OWN_JSON, 501),
    ],
)
def test_applies_strict_rule_when_run_command_sent(
    client: TestClient, *, path: str, headers: dict[str, str], status: int
) -> None:
    response = client.post(path, content=b"{}", headers=headers)

    assert response.status_code == status


@pytest.mark.parametrize("path", RUN_WRITES)
def test_requires_launch_cookie_when_run_command_sent(client: TestClient, path: str) -> None:
    client.cookies.clear()

    response = client.post(path, content=b"{}", headers=OWN_JSON)

    assert response.status_code == 401
    assert response.json()["type"] == "urn:agent-hub:problem:agent-session-unauthorized"


@pytest.mark.parametrize("path", RUN_WRITES)
def test_turns_run_commands_off_when_sessions_off(
    api_settings: ApiSettings, web_dist: Path, path: str
) -> None:
    app = create_app(replace(api_settings, sessions_off=True), web_dist=web_dist)
    with TestClient(app, base_url="http://127.0.0.1:7420") as off:
        response = off.post(path, content=b"{}", headers=OWN_JSON)
        listed = off.get("/api/v1/workflow-runs")

    assert response.status_code == 404
    assert response.json()["type"] == "urn:agent-hub:problem:run-control-off"
    assert listed.status_code != 404


ITEM_WRITES = (
    "/api/v1/projects/demo/skills/skill/demo/alpha/versions/0199f0a0-0000-7000-8000-00000000000a/restore",
    "/api/v1/projects/demo/skills/hook/project/pre-tool-use-1/versions/v-1/restore",
    "/api/v1/workflows/demo/review/versions/0199f0a0-0000-7000-8000-00000000000a/restore",
    "/api/v1/projects/demo/skills/drafts/skill-abc123/publish",
)


@pytest.mark.parametrize("path", ITEM_WRITES)
def test_is_item_write_when_restore_or_publish_path_posted(path: str) -> None:
    assert is_item_write("POST", path)
    assert is_strict_write("POST", path)
    assert not is_run_write("POST", path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", ITEM_WRITES[0]),
        ("POST", "/api/v1/projects/demo/skills/skill/demo/alpha/versions/v-1"),
        ("POST", "/api/v1/projects/demo/skills/skill/alpha/versions/v-1/restore"),
        ("POST", "/api/v1/projects/demo/skills/skill/demo/alpha/versions/v-1/restore/extra"),
        ("POST", "/api/v1/workflows/demo/review/versions//restore"),
        ("POST", "/api/v1/workflows/demo/a/b/versions/v-1/restore"),
        ("GET", ITEM_WRITES[3]),
        ("POST", "/api/v1/projects/demo/skills/drafts/skill-abc123"),
        ("POST", "/api/v1/projects/demo/skills/drafts//publish"),
        ("POST", "/api/v1/projects/demo/skills/drafts/skill-abc123/publish/extra"),
        ("POST", "/api/v1/projects/demo/drafts/skill-abc123/publish"),
    ],
)
def test_keeps_other_checks_when_not_item_write(method: str, path: str) -> None:
    assert not is_item_write(method, path)
    assert not is_strict_write(method, path)


async def _body_length_app(scope: Scope, receive: Receive, send: Send) -> None:
    # Not started as a context manager: the client sends no lifespan messages.
    body = await Request(scope, receive).body()
    await JSONResponse({"length": len(body)})(scope, receive, send)


def _capped_client() -> TestClient:
    return TestClient(
        LocalSecurityMiddleware(_body_length_app, port=7420), base_url="http://127.0.0.1:7420"
    )


def _streamed(size: int) -> Any:
    chunk = 65_536
    for start in range(0, size, chunk):
        yield b"a" * min(chunk, size - start)


def test_accepts_large_body_when_create_session_under_create_body_cap() -> None:
    body = b"a" * AGENT_SESSION_CREATE_BODY_BYTES

    client = _capped_client()
    sized = client.post("/api/v1/agent-sessions", content=body)
    streamed = client.post(
        "/api/v1/agent-sessions", content=_streamed(AGENT_SESSION_CREATE_BODY_BYTES)
    )

    # AC-419.6: ten images and ten files fit.
    assert AGENT_SESSION_CREATE_BODY_BYTES == 160 * 1024 * 1024
    assert (sized.status_code, sized.json()) == (200, {"length": len(body)})
    assert (streamed.status_code, streamed.json()) == (200, {"length": len(body)})


def test_refuses_body_when_create_session_over_create_body_cap() -> None:
    over = AGENT_SESSION_CREATE_BODY_BYTES + 1

    client = _capped_client()
    sized = client.post("/api/v1/agent-sessions", content=b"a" * over)
    streamed = client.post("/api/v1/agent-sessions", content=_streamed(over))

    for response in (sized, streamed):
        assert response.status_code == 413
        assert response.json()["title"] == "Request body too large"
        assert response.json()["detail"] == (
            f"Request bodies are limited to {AGENT_SESSION_CREATE_BODY_BYTES} bytes."
        )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/api/v1/agent-sessions"),
        ("POST", "/api/v1/agent-sessions/0123/messages/extra"),
        ("PUT", "/api/v1/agent-sessions/0123/messages"),
        ("POST", "/api/v1/agent-sessions/"),
        ("PATCH", "/api/v1/agent-sessions"),
    ],
)
def test_keeps_default_body_cap_when_other_route_or_method(method: str, path: str) -> None:
    over = MAX_BODY_BYTES + 1

    client = _capped_client()
    sized = client.request(method, path, content=b"a" * over)
    streamed = client.request(method, path, content=_streamed(over))

    for response in (sized, streamed):
        assert response.status_code == 413
        assert response.json()["detail"] == (
            f"Request bodies are limited to {MAX_BODY_BYTES} bytes."
        )


def test_caps_message_body_at_message_cap_when_images_may_be_pasted() -> None:
    path = "/api/v1/agent-sessions/0123/messages"

    client = _capped_client()
    at_cap = client.post(path, content=_streamed(AGENT_SESSION_MESSAGE_BODY_BYTES))
    over = client.post(path, content=_streamed(AGENT_SESSION_MESSAGE_BODY_BYTES + 1))

    # AC-419.6: ten images and ten files fit.
    assert AGENT_SESSION_MESSAGE_BODY_BYTES == 160 * 1024 * 1024
    assert at_cap.status_code == 200
    assert over.status_code == 413
    assert over.json()["detail"] == (
        f"Request bodies are limited to {AGENT_SESSION_MESSAGE_BODY_BYTES} bytes."
    )


# The playground's writes that rewrite a hub's files (AC-PG-23.3, AC-PG-37.1, AC-PG-38.4).
PLAYGROUND_HUB_WRITES = (
    ("POST", "/api/v1/hubs/hub-1/platform-sync"),
    ("POST", "/api/v1/hubs/hub-1/doctor-fix"),
    ("PUT", "/api/v1/projects/demo/config/local"),
    # AC-416.10: the environment edits are a hub registry write.
    ("POST", "/api/v1/projects/demo/config/environments"),
)
CHECK_RUN = "/api/v1/features/demo/demo-feature/acs/AC-7.1/check-runs"


# AC-PG-23.3, AC-PG-37.1: platform-sync, doctor-fix and the local config write take the hub
# registry's checks.
@pytest.mark.parametrize(("method", "path"), PLAYGROUND_HUB_WRITES)
def test_marks_hub_registry_write_when_playground_hub_write(method: str, path: str) -> None:
    assert is_hub_registry_write(method, path)
    assert not is_strict_write(method, path)


# AC-PG-23.3, AC-PG-37.1: only those exact method and path shapes are marked.
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/hubs/hub-1/platform-sync"),
        ("POST", "/api/v1/hubs/a/b/platform-sync"),
        ("POST", "/api/v1/hubs/hub-1/platform-sync/extra"),
        ("GET", "/api/v1/hubs/hub-1/doctor-fix"),
        ("POST", "/api/v1/hubs/hub-1/doctor-fixes"),
        ("GET", "/api/v1/projects/demo/config/local"),
        ("POST", "/api/v1/projects/demo/config/local"),
        ("PUT", "/api/v1/projects/a/b/config/local"),
        ("GET", "/api/v1/projects/demo/config"),
    ],
)
def test_keeps_default_checks_when_not_playground_hub_write(method: str, path: str) -> None:
    assert not is_hub_registry_write(method, path)


# AC-PG-23.3, AC-PG-37.1: a missing Origin is refused on those writes, as on the registry's.
@pytest.mark.parametrize(("method", "path"), PLAYGROUND_HUB_WRITES)
def test_refuses_playground_hub_write_when_origin_missing(
    client: TestClient, method: str, path: str
) -> None:
    client.headers.pop("Origin", None)

    response = client.request(method, path, json={})

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden origin"


# AC-PG-23.3, AC-PG-37.1: another loopback origin, even of this machine, is refused too.
@pytest.mark.parametrize(("method", "path"), PLAYGROUND_HUB_WRITES)
@pytest.mark.parametrize("origin", ["http://localhost:7420", "http://127.0.0.1:7421", "null"])
def test_refuses_playground_hub_write_when_origin_not_exactly_this_server(
    client: TestClient, *, method: str, path: str, origin: str
) -> None:
    response = client.request(method, path, json={}, headers={"Origin": origin})

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden origin"


# AC-PG-23.3, AC-PG-37.1: a cross-site fetch is refused even with this server's Origin.
@pytest.mark.parametrize(("method", "path"), PLAYGROUND_HUB_WRITES)
def test_refuses_playground_hub_write_when_fetch_site_cross_site(
    client: TestClient, method: str, path: str
) -> None:
    headers = {**OWN_JSON, "Sec-Fetch-Site": "cross-site"}

    response = client.request(method, path, json={}, headers=headers)

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden fetch site"


# AC-PG-23.3: the hub POSTs need a JSON body; the local config PUT is checked by origin only.
@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("POST", "/api/v1/hubs/hub-1/platform-sync", 415),
        ("POST", "/api/v1/hubs/hub-1/doctor-fix", 415),
    ],
)
def test_refuses_playground_hub_post_when_body_not_json(
    client: TestClient, *, method: str, path: str, status: int
) -> None:
    headers = {**OWN_JSON, "Content-Type": "text/plain"}

    response = client.request(method, path, content=b"{}", headers=headers)

    assert response.status_code == status


# AC-PG-23.3, AC-PG-37.1: from this server's own page, the write passes the checks.
@pytest.mark.parametrize(("method", "path"), PLAYGROUND_HUB_WRITES)
def test_passes_playground_hub_write_when_own_origin_and_json(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={}, headers=OWN_JSON)

    assert response.status_code not in {403, 415}


# AC-PG-37.1: an AC's check run starts a process, so it is a strict run write.
def test_marks_strict_run_write_when_post_to_check_run() -> None:
    assert is_run_write("POST", CHECK_RUN)
    assert is_strict_write("POST", CHECK_RUN)
    assert not is_run_write("GET", CHECK_RUN)
    assert not is_run_write("POST", "/api/v1/features/demo/a/b/acs/AC-7.1/check-runs")
    assert not is_run_write("POST", f"{CHECK_RUN}/extra")


# AC-PG-37.1: the check run takes the strict rule (own Origin, same-origin fetch, JSON body).
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Content-Type": "application/json"}, 403),
        ({**OWN_JSON, "Origin": "http://127.0.0.1:7421"}, 403),
        ({**OWN_JSON, "Sec-Fetch-Site": "same-site"}, 403),
        ({**OWN_JSON, "Content-Type": "text/plain"}, 415),
        (OWN_JSON, 501),
    ],
)
def test_applies_strict_rule_when_check_run_sent(
    client: TestClient, headers: dict[str, str], status: int
) -> None:
    response = client.post(CHECK_RUN, content=b"{}", headers=headers)

    assert response.status_code == status


# AC-PG-37.1: the check run needs the launch's cookie, as the other run writes.
def test_requires_launch_cookie_when_check_run_sent(client: TestClient) -> None:
    client.cookies.clear()

    response = client.post(CHECK_RUN, content=b"{}", headers=OWN_JSON)

    assert response.status_code == 401
    assert response.json()["type"] == "urn:agent-hub:problem:agent-session-unauthorized"


# AC-PG-37.1: with sessions off (the container), no check run starts.
def test_turns_check_run_off_when_sessions_off(api_settings: ApiSettings, web_dist: Path) -> None:
    app = create_app(replace(api_settings, sessions_off=True), web_dist=web_dist)
    with TestClient(app, base_url="http://127.0.0.1:7420") as off:
        response = off.post(CHECK_RUN, content=b"{}", headers=OWN_JSON)

    assert response.status_code == 404
    assert response.json()["type"] == "urn:agent-hub:problem:run-control-off"
