import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agent_hub.api.session_access import (
    AGENT_SESSION_READS,
    SessionAccessMiddleware,
    exchange_location,
    is_agent_session_path,
    read_refusal,
    session_cookie,
)

HOST = "127.0.0.1:7420"
TOKEN = "synthetic-launch-token-abcdefghijklmnopqrstuvwxyz01"  # noqa: S105 -- synthetic
RESTORE = "/api/v1/projects/demo/skills/agent/demo/scout/versions/v-1/restore"
WORKFLOW_RESTORE = "/api/v1/workflows/demo/review/versions/v-1/restore"
PUBLISH = "/api/v1/projects/demo/skills/drafts/agent-abc123/publish"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/agent-sessions", True),
        ("/api/v1/agent-sessions/cloud", True),
        ("/api/v1/agent-sessions/01929a4e-7a11-7c00-8a00-00000000a001/stream", True),
        ("/api/v1/agent-sessionsx", False),
        ("/api/v1/sessions", False),
        ("/agent-sessions", False),
    ],
)
def test_matches_prefix_only_when_path_checked(path: str, *, expected: bool) -> None:
    assert is_agent_session_path(path) is expected


@pytest.mark.parametrize(
    ("path", "query", "expected"),
    [
        ("/", b"token=abc", "/"),
        ("/sessions", b"tab=live&token=abc&q=a%20b", "/sessions?tab=live&q=a+b"),
        ("/", b"token=abc&token=def", "/"),
        ("//attacker.example", b"token=abc", "/attacker.example"),
        ("/\\attacker.example", b"token=abc", "/%5Cattacker.example"),
    ],
)
def test_drops_token_and_stays_on_server_when_location_built(
    path: str, query: bytes, expected: str
) -> None:
    assert exchange_location(path, query) == expected


def test_marks_cookie_http_only_strict_when_cookie_built() -> None:
    assert session_cookie("agent_hub_7420", "t") == (
        "agent_hub_7420=t; HttpOnly; SameSite=Strict; Path=/"
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://127.0.0.1:7421"},
        {"origin": "null"},
        {"sec-fetch-site": "same-site"},
        {"sec-fetch-site": "cross-site"},
    ],
)
def test_refuses_read_when_origin_foreign_or_site_not_own(headers: dict[str, str]) -> None:
    refusal = read_refusal(Headers({"host": HOST, **headers}))

    assert refusal is not None
    assert refusal[0] == 403


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"origin": f"http://{HOST}"},
        {"sec-fetch-site": "same-origin"},
        {"sec-fetch-site": "none"},
    ],
)
def test_accepts_read_when_origin_missing_or_own(headers: dict[str, str]) -> None:
    assert read_refusal(Headers({"host": HOST, **headers})) is None


async def _served(scope: Scope, receive: Receive, send: Send) -> None:
    await JSONResponse({"served": True})(scope, receive, send)


def _client(*, sessions_off: bool, signed_in: bool = False) -> TestClient:
    app = SessionAccessMiddleware(_served, port=7420, token=TOKEN, sessions_off=sessions_off)
    client = TestClient(app, base_url=f"http://{HOST}")
    if signed_in:
        client.cookies.set("agent_hub_7420", TOKEN)
    return client


@pytest.mark.parametrize("signed_in", [False, True])
@pytest.mark.parametrize("path", [RESTORE, WORKFLOW_RESTORE, PUBLISH])
def test_answers_hub_read_only_when_item_write_in_container(path: str, *, signed_in: bool) -> None:
    response = _client(sessions_off=True, signed_in=signed_in).post(path, json={})

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert (body["code"], body["title"]) == ("hub_read_only", "Item write refused")
    assert body["reason"]
    assert "served" not in body


@pytest.mark.parametrize("path", [RESTORE, WORKFLOW_RESTORE, PUBLISH])
def test_answers_unauthorized_when_item_write_without_cookie(path: str) -> None:
    response = _client(sessions_off=False).post(path, json={})

    assert response.status_code == 401
    assert response.json()["type"] == "urn:agent-hub:problem:agent-session-unauthorized"


def test_serves_item_write_when_cookie_matches() -> None:
    response = _client(sessions_off=False, signed_in=True).post(RESTORE, json={})

    assert response.json() == {"served": True}


def test_serves_item_version_read_when_in_container_without_cookie() -> None:
    response = _client(sessions_off=True).get(RESTORE.removesuffix("/v-1/restore"))

    assert response.json() == {"served": True}


# The scenario builder's writes (AGH-521): the cookie, and read-only in the container.
BUILDER_WRITES = (
    ("PUT", "/api/v1/scenarios/demo/walk"),
    ("POST", "/api/v1/scenarios/demo/walk/proposal/dismiss"),
    ("POST", "/api/v1/projects/demo/actions"),
    ("PUT", "/api/v1/projects/demo/actions/demo/send"),
    ("POST", "/api/v1/scenarios/demo/walk/migrate"),
    # AC-596.1.5: deleting a scenario removes its file from the hub.
    ("DELETE", "/api/v1/scenarios/demo/walk"),
)


@pytest.mark.parametrize(("method", "path"), BUILDER_WRITES)
def test_refuses_builder_write_when_no_cookie_or_in_container(method: str, path: str) -> None:
    unsigned = _client(sessions_off=False).request(method, path, json={})
    contained = _client(sessions_off=True, signed_in=True).request(method, path, json={})

    assert unsigned.status_code == 401
    assert (contained.status_code, contained.json()["code"]) == (409, "hub_read_only")


# A scenario run's values (ADR 0049): the launch cookie and this server's pages only, and
# off in the container, where no cookie exists; the run view itself stays open.
VALUES = "/api/v1/scenario-runs/walk-1/values"


@pytest.mark.parametrize(
    ("headers", "signed_in", "status"),
    [
        ({}, False, 401),
        ({"origin": "http://127.0.0.1:7421"}, True, 403),
        ({"sec-fetch-site": "same-site"}, True, 403),
    ],
)
def test_refuses_values_read_when_no_cookie_or_not_own_page(
    headers: dict[str, str], *, signed_in: bool, status: int
) -> None:
    response = _client(sessions_off=False, signed_in=signed_in).get(VALUES, headers=headers)

    assert response.status_code == status
    assert "served" not in response.json()


def test_serves_values_read_when_cookie_matches_and_origin_own() -> None:
    client = _client(sessions_off=False, signed_in=True)

    served = client.get(
        VALUES, headers={"origin": f"http://{HOST}", "sec-fetch-site": "same-origin"}
    )
    view = _client(sessions_off=False).get(VALUES.removesuffix("/values"))

    assert served.json() == {"served": True}
    assert view.json() == {"served": True}


@pytest.mark.parametrize("signed_in", [False, True])
def test_turns_values_read_off_when_in_container(*, signed_in: bool) -> None:
    response = _client(sessions_off=True, signed_in=signed_in).get(VALUES)

    assert response.status_code == 404
    assert response.json()["type"] == "urn:agent-hub:problem:run-control-off"


# The owner's writes (AGH-699, audit C-2): only the owner's own page makes them, and an exact
# Origin is something any local process can send, so they need the launch cookie too; the
# container mints no token, so there they are off, cookie or not.
OWNER_WRITES = (
    ("PUT", "/api/v1/projects/demo/config/local"),
    ("POST", "/api/v1/projects/demo/config/environments"),
    ("POST", "/api/v1/projects/demo/config/repos"),
    ("POST", "/api/v1/hubs/hub-1/platform-sync"),
    ("POST", "/api/v1/hubs/hub-1/doctor-fix"),
    ("POST", "/api/v1/learnings/learning-1/accept"),
    ("POST", "/api/v1/learnings/learning-1/reject"),
    ("POST", "/api/v1/learnings/decisions"),
    ("PUT", "/api/v1/tracker/linear"),
    ("DELETE", "/api/v1/tracker/linear"),
    ("PUT", "/api/v1/feature-names"),
)


@pytest.mark.parametrize(("method", "path"), OWNER_WRITES)
def test_answers_unauthorized_when_owner_write_without_cookie(method: str, path: str) -> None:
    response = _client(sessions_off=False).request(method, path, json={})

    assert response.status_code == 401
    assert response.json()["type"] == "urn:agent-hub:problem:agent-session-unauthorized"
    assert response.headers["www-authenticate"] == 'Cookie realm="agent-hub"'


@pytest.mark.parametrize(("method", "path"), OWNER_WRITES)
def test_serves_owner_write_when_cookie_matches(method: str, path: str) -> None:
    response = _client(sessions_off=False, signed_in=True).request(method, path, json={})

    assert response.json() == {"served": True}


@pytest.mark.parametrize("signed_in", [False, True])
@pytest.mark.parametrize(("method", "path"), OWNER_WRITES)
def test_turns_owner_write_off_when_in_container(
    method: str, path: str, *, signed_in: bool
) -> None:
    response = _client(sessions_off=True, signed_in=signed_in).request(method, path, json={})

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert (body["type"], body["title"]) == (
        "urn:agent-hub:problem:owner-writes-off",
        "Owner writes are off",
    )
    assert "served" not in body


@pytest.mark.parametrize("sessions_off", [False, True])
@pytest.mark.parametrize(
    "path", ["/api/v1/tracker/linear", "/api/v1/feature-names", "/api/v1/projects/demo/config"]
)
def test_serves_owner_page_read_when_no_cookie(path: str, *, sessions_off: bool) -> None:
    response = _client(sessions_off=sessions_off).get(path)

    assert response.json() == {"served": True}


# The agent-session read mark (ADR 0056 "Access"): written on every request passed on, True only
# for a GET or HEAD that the agent-session read checks pass.
SCREEN = "/api/v1/screens/sessions"
OWN_PAGE = {"origin": f"http://{HOST}"}


class MarkRecorder:
    """An inner app that answers every request and records the mark each one carried."""

    def __init__(self) -> None:
        self.marks: list[object] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.marks.append(scope.get(AGENT_SESSION_READS, "absent"))
        await _served(scope, receive, send)


def _marked_before(app: ASGIApp) -> ASGIApp:
    """``app`` behind an outer app that sets the mark to True first."""

    async def marked(scope: Scope, receive: Receive, send: Send) -> None:
        scope[AGENT_SESSION_READS] = True
        await app(scope, receive, send)

    return marked


@pytest.mark.parametrize(
    ("method", "headers", "signed_in", "sessions_off", "marked_before", "expected"),
    [
        ("GET", OWN_PAGE, True, False, False, True),
        ("HEAD", OWN_PAGE, True, False, False, True),
        ("POST", OWN_PAGE, True, False, False, False),
        ("GET", OWN_PAGE, False, False, False, False),
        ("GET", {"sec-fetch-site": "same-site"}, True, False, False, False),
        ("GET", OWN_PAGE, True, True, False, False),
        ("GET", OWN_PAGE, False, False, True, False),
    ],
    ids=[
        "get-own-page",
        "head-own-page",
        "post-own-page",
        "get-without-cookie",
        "get-same-site",
        "get-sessions-off",
        "marked-earlier-without-cookie",
    ],
)
def test_marks_agent_session_reads_only_when_get_passes_read_checks(
    method: str,
    headers: dict[str, str],
    *,
    signed_in: bool,
    sessions_off: bool,
    marked_before: bool,
    expected: bool,
) -> None:
    recorder = MarkRecorder()
    middleware = SessionAccessMiddleware(
        recorder, port=7420, token=TOKEN, sessions_off=sessions_off
    )
    client = TestClient(
        _marked_before(middleware) if marked_before else middleware, base_url=f"http://{HOST}"
    )
    if signed_in:
        client.cookies.set("agent_hub_7420", TOKEN)

    response = client.request(method, SCREEN, headers=headers)

    assert response.status_code == 200
    (mark,) = recorder.marks
    assert mark is expected
