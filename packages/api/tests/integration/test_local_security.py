from typing import Any

import pytest

from agent_hub.core.ingestion.hook_envelope import MAX_BODY_BYTES
from agent_hub.core.testing.read_model_builders import a_hub_view

HUB_PATH = {"path": "/home/demo/demo-hub"}


def test_answers_forbidden_and_changes_nothing_when_host_is_foreign(wired: Any) -> None:
    wired.hubs.hubs.append(a_hub_view())

    responses = [
        wired.client.get("/api/v1/hubs", headers={"Host": "attacker.example"}),
        wired.client.post("/api/v1/hubs", json=HUB_PATH, headers={"Host": "attacker.example"}),
        wired.client.get("/", headers={"Host": "attacker.example:7420"}),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    assert all(r.headers["content-type"] == "application/problem+json" for r in responses)
    assert wired.hubs.calls == []


@pytest.mark.parametrize("method", ["post", "delete"])
def test_answers_forbidden_and_changes_nothing_when_origin_is_foreign(
    wired: Any, method: str
) -> None:
    wired.hubs.hubs.append(a_hub_view())
    path = "/api/v1/hubs" if method == "post" else f"/api/v1/hubs/{a_hub_view().id}"
    options = {"json": HUB_PATH} if method == "post" else {}

    response = wired.client.request(
        method, path, headers={"Origin": "http://attacker.example"}, **options
    )

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden origin"
    assert wired.hubs.calls == []
    assert len(wired.hubs.hubs) == 1


def test_accepts_write_when_origin_is_own(wired: Any) -> None:
    wired.hubs.hubs.append(a_hub_view())

    response = wired.client.post(
        "/api/v1/hubs", json=HUB_PATH, headers={"Origin": "http://localhost:7420"}
    )

    assert response.status_code == 201
    assert wired.hubs.calls == [("register_hub", HUB_PATH["path"])]


def test_accepts_read_when_origin_is_foreign(wired: Any) -> None:
    # A cross-site GET is answered, but without CORS headers the page cannot read it.
    response = wired.client.get("/api/v1/hubs", headers={"Origin": "http://attacker.example"})

    assert response.status_code == 200
    assert not [name for name in response.headers if name.lower().startswith("access-control")]


def test_answers_too_large_problem_when_content_length_over_cap(wired: Any) -> None:
    body = b"{" + b" " * MAX_BODY_BYTES + b"}"

    response = wired.client.post(
        "/api/v1/hubs", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert response.json()["title"] == "Request body too large"
    assert wired.hubs.calls == []


def test_answers_too_large_problem_when_streamed_body_passes_cap(wired: Any) -> None:
    def chunks() -> Any:
        yield b'{"path": "'
        for _ in range(MAX_BODY_BYTES // 65_536 + 1):
            yield b"a" * 65_536
        yield b'"}'

    response = wired.client.post(
        "/api/v1/hubs", content=chunks(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert wired.hubs.calls == []


def test_sends_no_store_and_policy_headers_when_api_answers(wired: Any) -> None:
    response = wired.client.get("/api/v1/hubs")

    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_sends_policy_without_no_store_when_app_page_served(wired: Any) -> None:
    response = wired.client.get("/sessions/abc")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "connect-src 'self'" in response.headers["content-security-policy"]


def test_sends_no_cors_headers_when_preflight_requested(wired: Any) -> None:
    response = wired.client.options(
        "/api/v1/hubs",
        headers={
            "Origin": "http://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert not [name for name in response.headers if name.lower().startswith("access-control")]
