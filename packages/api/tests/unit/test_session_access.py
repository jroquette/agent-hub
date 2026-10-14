import pytest
from starlette.datastructures import Headers

from agent_hub.api.session_access import (
    exchange_location,
    is_agent_session_path,
    read_refusal,
    session_cookie,
)

HOST = "127.0.0.1:7420"


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
