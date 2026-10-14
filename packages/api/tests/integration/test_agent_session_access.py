"""Access to the agent-session routes (AC-165.8-.10, .13; P6, L1, L2): the token-to-cookie
exchange, the cookie on every route, the Origin rules, container mode, other loopback binds.

The app is ``create_app`` with recording mocks for the two command ports, so a refusal can be
proven to happen before any port is called. Every token here is synthetic.
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.app import create_app
from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.openapi_paths import AGENT_SESSION_PATHS
from agent_hub.api.server import LoopbackServer, bind_address
from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.agent_sessions.agent_session import (
    AgentSessionList,
    CloudSessionList,
    MessageAccepted,
    ResumableList,
    WorkdirList,
)
from agent_hub.core.agent_sessions.cloud import CloudSessionCommands
from agent_hub.core.agent_sessions.control import AgentSessionCommands
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.agent_sessions.records import LogRecordPage, StreamItem
from agent_hub.core.testing.read_model_builders import (
    AGENT_SESSION_ID,
    WORKDIR_ID,
    a_cloud_session,
    a_workdir,
    an_agent_session,
)

PORT = 7420
BASE_URL = f"http://127.0.0.1:{PORT}"
OWN_ORIGIN = "http://127.0.0.1:7420"
TOKEN = "synthetic-launch-token-abcdefghijklmnopqrstuvwxyz01"  # noqa: S105 -- synthetic
COOKIE = cookie_name(PORT)
JSON = "application/json"
OFF_TYPE = "urn:agent-hub:problem:agent-sessions-off"
UNAUTHORIZED_TYPE = "urn:agent-hub:problem:agent-session-unauthorized"

BODIES: dict[tuple[str, str], object] = {
    ("post", ""): {"project": "demo", "workdir_id": WORKDIR_ID},
    ("post", "/cloud"): {"project": "demo", "workdir_id": WORKDIR_ID, "task": "Upgrade the linter"},
    ("post", "/cloud/{cloud_id}/messages"): {"text": "Also the docs"},
    ("post", "/{agent_session_id}/messages"): {"text": "Run the tests."},
    ("post", "/{agent_session_id}/permissions/{request_id}"): {"decision": "allow"},
    ("post", "/{agent_session_id}/settings"): {"mode": "plan"},
}
QUERIES: dict[str, dict[str, str]] = {
    "/workdirs": {"project": "demo"},
    "/resumable": {"project": "demo", "workdir_id": WORKDIR_ID},
}
PREFIX = "/api/v1/agent-sessions"
ROUTES = sorted((method, path.removeprefix(PREFIX)) for method, path in AGENT_SESSION_PATHS)
WRITES = [(method, path) for method, path in ROUTES if method != "get"]
STREAM = f"{PREFIX}/{AGENT_SESSION_ID}/stream"


def _url(path: str) -> str:
    filled = (
        path.replace("{agent_session_id}", AGENT_SESSION_ID)
        .replace("{request_id}", "req-1")
        .replace("{cloud_id}", "cse_01synthetic")
    )
    return f"{PREFIX}{filled}"


def _request(
    client: TestClient, method: str, path: str, *, headers: dict[str, str] | None = None
) -> Any:
    body = BODIES.get((method, path), {} if method == "post" else None)
    sent = dict(headers or {})
    content = None
    if body is not None:
        content = json.dumps(body).encode()
        sent.setdefault("Content-Type", JSON)
    return client.request(
        method.upper(), _url(path), content=content, params=QUERIES.get(path), headers=sent
    )


def _control() -> Mock:
    control = Mock(spec=AgentSessionCommands)
    session = an_agent_session()
    control.workdirs.return_value = WorkdirList(items=(a_workdir(),))
    control.capabilities.return_value = DriverCapabilities(available=True, engine="in-memory")
    control.resumable.return_value = ResumableList(items=())
    control.list_sessions.return_value = AgentSessionList(items=(session,))
    control.create.return_value = session
    control.snapshot.return_value = session
    control.delete.return_value = None
    control.events.return_value = LogRecordPage(items=(), next_after=None)
    control.send.return_value = MessageAccepted(seq=5)
    for method in ("interrupt", "answer", "change_settings", "close"):
        getattr(control, method).return_value = session
    return control


async def _no_items() -> AsyncIterator[StreamItem]:
    # A subscription that ends at once, so the stream's response completes.
    for item in ():
        yield item


def _cloud() -> Mock:
    cloud = Mock(spec=CloudSessionCommands)
    cloud.list_cloud.return_value = CloudSessionList(items=(a_cloud_session(),))
    cloud.start.return_value = a_cloud_session()
    cloud.follow_up.return_value = a_cloud_session(followups=1)
    return cloud


class Guarded:
    """The app's client and the two recording ports behind it."""

    def __init__(self, client: TestClient, control: Mock, cloud: Mock) -> None:
        self.client = client
        self.control = control
        self.cloud = cloud

    def calls(self) -> list[Any]:
        return [*self.control.mock_calls, *self.cloud.mock_calls]


def _settings(api_settings: ApiSettings, **changes: Any) -> ApiSettings:
    return replace(api_settings, **({"session_token": TOKEN} | changes))


@pytest.fixture
def guarded(api_settings: ApiSettings, web_dist: Path) -> Iterator[Guarded]:
    control, cloud = _control(), _cloud()
    ports = ApiPorts(agent_sessions=control, cloud_sessions=cloud)
    app = create_app(_settings(api_settings), ports=ports, web_dist=web_dist)
    with TestClient(app, base_url=BASE_URL, follow_redirects=False) as client:
        yield Guarded(client, control, cloud)


@pytest.fixture
def signed_in(guarded: Guarded) -> Guarded:
    guarded.client.cookies.set(COOKIE, TOKEN)
    return guarded


# The token exchange, AC-165.8.


def test_sets_cookie_and_redirects_when_exchange_token_valid(guarded: Guarded) -> None:
    response = guarded.client.get("/sessions", params={"token": TOKEN, "tab": "live"})

    assert response.status_code == 303
    assert response.headers["location"] == "/sessions?tab=live"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}={TOKEN};")
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "samesite=strict", "path=/"} <= attributes


def test_redirects_to_root_without_query_when_exchange_token_only_parameter(
    guarded: Guarded,
) -> None:
    response = guarded.client.get("/", params={"token": TOKEN})

    assert (response.status_code, response.headers["location"]) == (303, "/")


def test_redirects_once_without_cookie_when_exchange_token_invalid(guarded: Guarded) -> None:
    response = guarded.client.get("/", params={"token": TOKEN[:-1] + "X"})
    followed = guarded.client.get(response.headers["location"])

    assert response.status_code == 303
    assert "set-cookie" not in response.headers
    assert response.headers["location"] == "/"
    assert followed.status_code == 200
    assert "set-cookie" not in followed.headers


def test_keeps_redirect_on_this_server_when_exchange_path_starts_with_slashes(
    guarded: Guarded,
) -> None:
    response = guarded.client.get("//attacker.example/%5Cx", params={"token": TOKEN})

    location = response.headers["location"]
    assert response.status_code == 303
    assert location.startswith("/")
    assert not location.startswith("//")
    assert "\\" not in location


def test_ignores_token_query_when_exchange_requested_on_api_path(signed_in: Guarded) -> None:
    response = signed_in.client.get(f"{PREFIX}/capabilities", params={"token": TOKEN})

    assert response.status_code == 200
    assert "set-cookie" not in response.headers


# The cookie on every route, AC-165.9.


@pytest.mark.parametrize("cookie", [None, "wrong", "other_port"])
@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_requires_cookie_when_missing_wrong_or_other_port(
    guarded: Guarded, *, method: str, path: str, cookie: str | None
) -> None:
    if cookie == "wrong":
        guarded.client.cookies.set(COOKIE, TOKEN[:-1] + "X")
    elif cookie == "other_port":
        guarded.client.cookies.set(cookie_name(PORT + 1), TOKEN)

    response = _request(guarded.client, method, path, headers={"Origin": OWN_ORIGIN})

    assert response.status_code == 401, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == UNAUTHORIZED_TYPE
    assert TOKEN not in response.text
    assert guarded.calls() == []


@pytest.mark.parametrize(
    ("method", "path"), [r for r in ROUTES if r[1] != "/{agent_session_id}/stream"]
)
def test_reaches_port_when_cookie_valid_and_requires_cookie_checked(
    signed_in: Guarded, method: str, path: str
) -> None:
    response = _request(signed_in.client, method, path, headers={"Origin": OWN_ORIGIN})

    assert response.status_code < 300, response.text
    assert len(signed_in.calls()) == 1


# The Origin and media type rules, AC-165.10 and E4.


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://attacker.example"},
        {"Origin": "http://127.0.0.1:7421"},
        {"Origin": "http://localhost:7420"},
        {"Origin": OWN_ORIGIN, "Sec-Fetch-Site": "cross-site"},
        {"Origin": OWN_ORIGIN, "Sec-Fetch-Site": "same-site"},
    ],
)
@pytest.mark.parametrize(("method", "path"), WRITES)
def test_refuses_write_when_origin_missing_foreign_or_cross_site(
    signed_in: Guarded, *, method: str, path: str, headers: dict[str, str]
) -> None:
    response = _request(signed_in.client, method, path, headers=headers)

    assert response.status_code == 403, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert signed_in.calls() == []


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded"])
@pytest.mark.parametrize(("method", "path"), [w for w in WRITES if w[0] == "post"])
def test_answers_unsupported_media_when_origin_own_and_write_not_json(
    signed_in: Guarded, *, method: str, path: str, content_type: str | None
) -> None:
    headers = {"Origin": OWN_ORIGIN}
    if content_type is not None:
        headers["Content-Type"] = content_type
    response = signed_in.client.post(_url(path), content=b"{}", headers=headers)

    assert response.status_code == 415, response.text
    assert signed_in.calls() == []


def test_accepts_write_when_origin_own_and_fetch_same_origin(signed_in: Guarded) -> None:
    headers = {"Origin": OWN_ORIGIN, "Sec-Fetch-Site": "same-origin"}

    response = _request(signed_in.client, "post", "/{agent_session_id}/close", headers=headers)

    assert response.status_code == 200, response.text
    signed_in.control.close.assert_awaited_once()


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://attacker.example"},
        {"Origin": "http://127.0.0.1:5173"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Origin": OWN_ORIGIN, "Sec-Fetch-Site": "same-site"},
    ],
)
def test_refuses_stream_when_origin_foreign_or_cross_site(
    signed_in: Guarded, headers: dict[str, str]
) -> None:
    response = signed_in.client.get(STREAM, headers=headers)

    assert response.status_code == 403, response.text
    assert signed_in.calls() == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Sec-Fetch-Site": "same-origin"},
        {"Origin": OWN_ORIGIN, "Sec-Fetch-Site": "same-origin"},
    ],
)
def test_streams_when_origin_missing_and_cookie_valid(
    signed_in: Guarded, headers: dict[str, str]
) -> None:
    signed_in.control.subscribe.return_value = _no_items()

    response = signed_in.client.get(STREAM, headers=headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    signed_in.control.subscribe.assert_awaited_once()


def test_refuses_read_when_origin_foreign(signed_in: Guarded) -> None:
    response = signed_in.client.get(
        f"{PREFIX}/capabilities", headers={"Origin": "http://evil.test"}
    )

    assert response.status_code == 403
    assert signed_in.calls() == []


def test_answers_403_before_cookie_when_host_foreign(signed_in: Guarded) -> None:
    response = signed_in.client.get(f"{PREFIX}/capabilities", headers={"Host": "attacker.example"})

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden host"


# The routes that existed before, AC-165.12.


def test_serves_existing_route_without_cookie_when_sessions_guarded(guarded: Guarded) -> None:
    response = guarded.client.get("/api/v1/openapi.json")

    assert response.status_code == 200


# Container mode and other loopback binds, AC-165.13 and E2.


@pytest.mark.parametrize("cookie", [True, False])
@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_answers_off_problem_when_container_off(
    api_settings: ApiSettings, web_dist: Path, *, method: str, path: str, cookie: bool
) -> None:
    control, cloud = _control(), _cloud()
    settings = _settings(api_settings, session_token=None, sessions_off=True)
    app = create_app(
        settings, ports=ApiPorts(agent_sessions=control, cloud_sessions=cloud), web_dist=web_dist
    )
    with TestClient(app, base_url=BASE_URL) as client:
        if cookie:
            client.cookies.set(COOKIE, TOKEN)
        response = _request(client, method, path, headers={"Origin": OWN_ORIGIN})

    assert response.status_code == 404, response.text
    assert response.json()["type"] == OFF_TYPE
    assert [*control.mock_calls, *cloud.mock_calls] == []


def test_requires_cookie_when_no_token_configured(
    api_settings: ApiSettings, web_dist: Path
) -> None:
    control = _control()
    settings = _settings(api_settings, session_token=None)
    app = create_app(settings, ports=ApiPorts(agent_sessions=control), web_dist=web_dist)
    with TestClient(app, base_url=BASE_URL) as client:
        client.cookies.set(COOKIE, "")
        response = client.get(f"{PREFIX}/capabilities")

    assert response.status_code == 401
    assert control.mock_calls == []


def _loopback_available(host: str) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
    except OSError:
        return False
    return True


def _get(url: str, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 -- a loopback URL built here
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 -- same
            status: int = response.status
            return status
    except urllib.error.HTTPError as error:
        return error.code


@pytest.mark.parametrize("bind", ["127.0.0.2", "::1"])
def test_requires_cookie_when_bound_to_other_loopback(
    api_settings: ApiSettings, web_dist: Path, bind: str
) -> None:
    if not _loopback_available(bind):
        pytest.skip(f"{bind} cannot be bound here")
    sock = bind_address(bind, 0)
    port = sock.getsockname()[1]
    control = _control()
    settings = _settings(api_settings, port=port)
    server = LoopbackServer(
        create_app(settings, ports=ApiPorts(agent_sessions=control), web_dist=web_dist), sock
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    shown = f"[{bind}]" if ":" in bind else bind
    url = f"http://{shown}:{port}{PREFIX}/capabilities"
    host = {"Host": f"127.0.0.1:{port}"}
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        without = _get(url, host)
        with_cookie = _get(url, host | {"Cookie": f"{cookie_name(port)}={TOKEN}"})
    finally:
        server.stop()
        thread.join(timeout=10)

    assert (without, with_cookie) == (401, 200)
    control.capabilities.assert_awaited_once()
