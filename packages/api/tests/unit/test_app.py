import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.app import create_app
from agent_hub.api.change_feed import ChangeFeed
from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.openapi_paths import SERVED_PATHS
from agent_hub.api.settings import ApiSettings

# Valid bodies, so validation passes and the stub itself answers.
BODIES: dict[tuple[str, str], object] = {
    ("post", "/api/v1/events/hooks"): {
        "v": 1,
        "project": "demo",
        "sent_at": "2026-10-11T10:00:00Z",
        "hook": {"hook_event_name": "Stop"},
    },
    ("post", "/api/v1/hubs"): {"path": "/home/demo/demo-hub"},
    ("post", "/api/v1/learnings/{learning_id}/accept"): {"target": "learnings/"},
    ("post", "/api/v1/learnings/{learning_id}/reject"): {"reason": "Duplicate of another note"},
    ("post", "/api/v1/agent-sessions"): {"project": "demo", "workdir_id": "0123456789abcdef"},
    ("post", "/api/v1/agent-sessions/cloud"): {
        "project": "demo",
        "workdir_id": "0123456789abcdef",
        "task": "Upgrade the linter",
    },
    ("post", "/api/v1/agent-sessions/cloud/{cloud_id}/messages"): {"text": "Also the docs"},
    ("post", "/api/v1/agent-sessions/{agent_session_id}/messages"): {"text": "Run the tests."},
    ("post", "/api/v1/agent-sessions/{agent_session_id}/permissions/{request_id}"): {
        "decision": "allow"
    },
    ("post", "/api/v1/agent-sessions/{agent_session_id}/settings"): {"mode": "plan"},
    # Bodiless agent-session writes still send JSON (the access rules want it).
    ("post", "/api/v1/agent-sessions/{agent_session_id}/interrupt"): {},
    ("post", "/api/v1/agent-sessions/{agent_session_id}/close"): {},
}
OWN_ORIGIN = {"Origin": "http://127.0.0.1:7420"}
QUERIES = {
    "/api/v1/search": {"q": "make"},
    "/api/v1/projects/{project}/brain/note": {"path": "index.md"},
    "/api/v1/agent-sessions/workdirs": {"project": "demo"},
    "/api/v1/agent-sessions/resumable": {"project": "demo", "workdir_id": "0123456789abcdef"},
}
# Agent session ids are UUIDs (the route's convertor); the other ids take any text.
AGENT_SESSION_ID = "01929a4e-7a11-7c00-8a00-00000000a001"


def _concrete(path: str) -> str:
    path = path.replace("{agent_session_id}", AGENT_SESSION_ID)
    names = ("hub_id", "project", "session_id", "run_id", "approval_id", "learning_id", "slug")
    for name in (*names, "request_id", "cloud_id"):
        path = path.replace(f"{{{name}}}", f"{name}-1")
    return path


@pytest.mark.parametrize(("method", "path"), sorted(SERVED_PATHS))
def test_answers_not_implemented_problem_when_route_is_a_stub(
    client: TestClient, method: str, path: str
) -> None:
    url = _concrete(path)

    response = client.request(
        method,
        url,
        json=BODIES.get((method, path)),
        params=QUERIES.get(path),
        headers=OWN_ORIGIN,  # the learning actions need it (S7); the other routes ignore it
    )

    assert response.status_code == 501, response.text
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["status"] == 501
    assert problem["title"] == "Not implemented in this build"
    assert problem["instance"] == url


def test_serves_openapi_document_when_requested(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"] == {"title": "agent-hub", "version": "0.1.0"}


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_serves_app_instead_of_docs_page_when_requested(client: TestClient, path: str) -> None:
    # The SPA answers every app route with its index page; FastAPI's docs pages are off.
    response = client.get(path)

    assert response.status_code == 200
    assert "<title>agent-hub</title>" in response.text
    assert "swagger" not in response.text.lower()
    assert "redoc" not in response.text.lower()


def test_serves_no_root_openapi_document_when_requested(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 404


def test_keeps_ports_when_app_created(api_settings: ApiSettings) -> None:
    ports = ApiPorts()

    assert create_app(api_settings, ports=ports).state.ports is ports


def test_keeps_settings_when_app_created(api_settings: ApiSettings) -> None:
    assert create_app(api_settings).state.settings is api_settings


def test_closes_change_feed_when_app_shuts_down(api_settings: ApiSettings, fakes: Any) -> None:
    reader = fakes.EventReader()
    feed = ChangeFeed(reader, timer=fakes.Clock())
    app = create_app(api_settings, ports=ApiPorts(event_reader=reader, change_feed=feed))

    with TestClient(app):
        assert asyncio.run(feed.wait_beyond(0, deadline=1)) == 0

    assert asyncio.run(feed.wait_beyond(0, deadline=1)) is None
