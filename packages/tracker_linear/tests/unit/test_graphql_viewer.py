"""The Linear connection check: the key's user and workspace, or the transport's failure."""

import json
from collections.abc import Mapping

import pytest

from agent_hub.core.errors import TrackerError
from agent_hub.tracker_linear.graphql_transport import Post
from agent_hub.tracker_linear.graphql_viewer import LinearAccount, linear_account

KEY = "lin" + "_api_" + "k" * 20


def _post(status: int, payload: object, seen: list[Mapping[str, str]]) -> Post:
    def post(
        url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        del url, body, timeout_s
        seen.append(headers)
        return status, json.dumps(payload).encode()

    return post


def test_returns_account_when_linear_accepts_key() -> None:
    seen: list[Mapping[str, str]] = []
    data = {
        "viewer": {"name": "Ada", "email": "ada@example.com"},
        "organization": {"name": "Example", "urlKey": "example"},
    }

    account = linear_account({"LINEAR_API_KEY": KEY}, post=_post(200, {"data": data}, seen))

    assert account == LinearAccount("Ada", "ada@example.com", "Example", "example")
    assert seen[0]["Authorization"] == KEY


def test_raises_unauthorized_when_linear_refuses_key() -> None:
    with pytest.raises(TrackerError) as raised:
        linear_account({"LINEAR_API_KEY": KEY}, post=_post(401, {}, []))

    assert raised.value.kind == "unauthorized"
    assert KEY not in str(raised.value)


def test_raises_not_connected_when_no_key() -> None:
    seen: list[Mapping[str, str]] = []
    with pytest.raises(TrackerError) as raised:
        linear_account({}, post=_post(200, {}, seen))

    assert raised.value.kind == "not_connected"
    assert seen == []
