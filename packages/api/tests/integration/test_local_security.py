import json
import re
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
        "/api/v1/hubs", json=HUB_PATH, headers={"Origin": "http://127.0.0.1:7420"}
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
        "/api/v1/hubs",
        content=body,
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:7420"},
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
        "/api/v1/hubs",
        content=chunks(),
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:7420"},
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


# The two learning actions open a hub PR, so they take stricter checks than the other writes
# (S7, E9): the server's own Origin, no cross-site fetch and a JSON body.
OWN_ORIGIN = "http://127.0.0.1:7420"
type Action = tuple[str, dict[str, str]]
LEARNING_ACTIONS: list[Action] = [
    ("/api/v1/learnings/learning-1/accept", {"target": "learnings/"}),
    ("/api/v1/learnings/learning-1/reject", {"reason": "Already in the brain"}),
]
# The policy as v0.9.0 serves it; control-plane clarity adds routes, never a source.
V0_9_0_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)


def _post_action(wired: Any, action: Action, **headers: str) -> Any:
    wired.wire(learning_decisions=wired.decisions)
    sent = {"Origin": OWN_ORIGIN, "Content-Type": "application/json", **headers}
    path, body = action
    return wired.client.post(path, content=json.dumps(body), headers=sent)


@pytest.mark.parametrize("action", LEARNING_ACTIONS)
def test_accepts_learning_actions_when_origin_own_and_body_json(wired: Any, action: Action) -> None:
    response = _post_action(wired, action, **{"Sec-Fetch-Site": "same-origin"})

    assert response.status_code == 201
    assert len(wired.decisions.calls) == 1


@pytest.mark.parametrize("action", LEARNING_ACTIONS)
def test_accepts_learning_actions_when_json_has_charset_and_no_fetch_metadata(
    wired: Any, action: Action
) -> None:
    response = _post_action(wired, action, **{"Content-Type": "Application/JSON; charset=utf-8"})

    assert response.status_code == 201


@pytest.mark.parametrize("action", LEARNING_ACTIONS)
def test_refuses_learning_actions_when_origin_missing(wired: Any, action: Action) -> None:
    wired.wire(learning_decisions=wired.decisions)

    path, body = action

    response = wired.client.post(path, json=body)

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Forbidden origin"
    assert wired.decisions.calls == []


@pytest.mark.parametrize(
    "origin",
    [
        "http://attacker.example",
        "null",
        "http://localhost:7420",  # another loopback name than the Host the request names
        "https://127.0.0.1:7420",
        "http://127.0.0.1:5173",
    ],
)
@pytest.mark.parametrize("action", LEARNING_ACTIONS)
def test_refuses_learning_actions_when_origin_foreign(
    wired: Any, action: Action, origin: str
) -> None:
    response = _post_action(wired, action, Origin=origin)

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden origin"
    assert wired.decisions.calls == []


@pytest.mark.parametrize("site", ["cross-site", "same-site", "none"])
@pytest.mark.parametrize("action", LEARNING_ACTIONS)
def test_refuses_learning_actions_when_fetch_is_cross_site(
    wired: Any, action: Action, site: str
) -> None:
    response = _post_action(wired, action, **{"Sec-Fetch-Site": site})

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden fetch site"
    assert wired.decisions.calls == []


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None],
)
@pytest.mark.parametrize("action", LEARNING_ACTIONS)
def test_refuses_learning_actions_when_content_type_is_text(
    wired: Any, action: Action, content_type: str | None
) -> None:
    wired.wire(learning_decisions=wired.decisions)
    headers = {"Origin": OWN_ORIGIN}
    if content_type is not None:
        headers["Content-Type"] = content_type

    path, body = action

    response = wired.client.post(path, content=json.dumps(body), headers=headers)

    assert response.status_code == 415
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Unsupported media type"
    assert wired.decisions.calls == []


@pytest.mark.parametrize("action", LEARNING_ACTIONS)
def test_refuses_learning_actions_when_host_foreign(wired: Any, action: Action) -> None:
    response = _post_action(
        wired, action, Host="attacker.example", Origin="http://attacker.example"
    )

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden host"
    assert wired.decisions.calls == []


@pytest.mark.parametrize("action", LEARNING_ACTIONS)
def test_refuses_learning_actions_when_body_over_cap(wired: Any, action: Action) -> None:
    wired.wire(learning_decisions=wired.decisions)
    oversized = b"{" + b" " * MAX_BODY_BYTES + b"}"

    response = wired.client.post(
        action[0],
        content=oversized,
        headers={"Origin": OWN_ORIGIN, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert wired.decisions.calls == []


# A11: the hub registry writes need this server's exact Origin, a missing one refused too (a
# registered hub is a folder agent sessions may start in). The Origin-less hook POST stays
# accepted: test_hooks_ingestion.
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "http://localhost:7420"},
        {"Origin": "http://127.0.0.1:7420", "Sec-Fetch-Site": "same-site"},
    ],
)
@pytest.mark.parametrize("method", ["post", "delete"])
def test_refuses_hub_registry_write_when_origin_not_exactly_own(
    wired: Any, method: str, headers: dict[str, str]
) -> None:
    wired.hubs.hubs.append(a_hub_view())
    path = "/api/v1/hubs" if method == "post" else f"/api/v1/hubs/{a_hub_view().id}"
    options = {"json": HUB_PATH} if method == "post" else {}

    response = wired.client.request(method, path, headers=headers, **options)

    assert response.status_code == 403
    assert wired.hubs.calls == []
    assert len(wired.hubs.hubs) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/learnings",
        "/api/v1/learnings/learning-1",
        "/api/v1/sessions/session-1/problems",
        "/api/v1/projects/demo/brain",
        "/api/v1/projects/demo/brain/note?path=index.md",
        "/api/v1/features/demo/feature-1/tickets",
        "/api/v1/projects/demo/skills",
        "/api/v1/projects/demo/skills/skill/hub-workflow/alpha",
        "/api/v1/projects/demo/skills/skill/hub-workflow/alpha/files/0123456789abcdef",
    ],
)
def test_keeps_csp_when_clarity_routes_served(wired: Any, path: str) -> None:
    response = wired.client.get(path)

    assert response.headers["content-security-policy"] == V0_9_0_CSP
    assert response.headers["cache-control"] == "no-store"


AGENT_SESSION_ID_PATH = "/api/v1/agent-sessions/0192f3a0-0000-7000-8000-000000000001"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/agent-sessions",
        "/api/v1/agent-sessions/capabilities",
        "/api/v1/agent-sessions/workdirs?project=demo",
        "/api/v1/agent-sessions/cloud",
        AGENT_SESSION_ID_PATH,
        f"{AGENT_SESSION_ID_PATH}/events",
    ],
)
def test_keeps_csp_when_agent_session_routes_served(wired: Any, path: str) -> None:
    response = wired.client.get(path)

    assert response.headers["content-security-policy"] == V0_9_0_CSP
    assert response.headers["cache-control"] == "no-store"


def test_keeps_csp_when_agent_session_page_served(wired: Any) -> None:
    response = wired.client.get("/agent-sessions/0192f3a0-0000-7000-8000-000000000001")

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == V0_9_0_CSP


def _pre_existing_reads(wired: Any) -> list[str]:
    """Every ``GET`` of the document outside the agent sessions, path parameters filled in, the
    endless streams left out."""
    paths: dict[str, dict[str, object]] = wired.client.app.openapi()["paths"]
    return [
        re.sub(r"\{[^}]+\}", "demo", path)
        for path, item in sorted(paths.items())
        if "get" in item
        and not path.startswith("/api/v1/agent-sessions")
        and not path.endswith("/stream")
    ]


def test_keeps_routes_unchanged_when_no_cookie(wired: Any) -> None:
    # The Origin-less hook POST without a cookie: test_hooks_ingestion (composed app, no token).
    wired.hubs.hubs.append(a_hub_view())
    reads = _pre_existing_reads(wired)
    signed_in = [(path, wired.client.get(path)) for path in reads]

    wired.client.cookies.clear()
    without = [(path, wired.client.get(path)) for path in reads]

    assert len(reads) > 20
    assert [(path, r.status_code, r.content) for path, r in without] == [
        (path, r.status_code, r.content) for path, r in signed_in
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/projects/demo/skills",
        "/projects/demo/skills/skill/hub-workflow/alpha",
        "/knowledge/skills",
    ],
)
def test_keeps_csp_when_skills_deep_link_served(wired: Any, path: str) -> None:
    response = wired.client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == V0_9_0_CSP
