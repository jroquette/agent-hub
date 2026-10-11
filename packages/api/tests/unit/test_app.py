import pytest
from fastapi.testclient import TestClient

from agent_hub.api.app import create_app
from agent_hub.api.openapi_paths import P2_PATHS
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
}
QUERIES = {"/api/v1/search": {"q": "make"}}


def _concrete(path: str) -> str:
    for name in ("hub_id", "project", "session_id", "run_id", "approval_id", "learning_id", "slug"):
        path = path.replace(f"{{{name}}}", f"{name}-1")
    return path


@pytest.mark.parametrize(("method", "path"), sorted(P2_PATHS))
def test_answers_not_implemented_problem_when_route_is_a_stub(
    client: TestClient, method: str, path: str
) -> None:
    url = _concrete(path)

    response = client.request(
        method, url, json=BODIES.get((method, path)), params=QUERIES.get(path)
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


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_serves_no_docs_page_when_requested(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_keeps_settings_when_app_created(api_settings: ApiSettings) -> None:
    assert create_app(api_settings).state.settings is api_settings
