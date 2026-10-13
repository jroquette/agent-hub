from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent_hub.api.app import create_app
from agent_hub.api.local_security import (
    CONTENT_SECURITY_POLICY,
    WEBSOCKET_POLICY_VIOLATION,
    allowed_hosts,
    allowed_origins,
    is_json_media_type,
    is_strict_write,
    parse_allowed_hosts,
)
from agent_hub.api.settings import ApiSettings


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
