import base64

import pytest

from agent_hub.core.errors import AgentHubError
from agent_hub.core.readmodels.cursor import (
    Cursor,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)
from agent_hub.core.readmodels.page import MAX_CURSOR_CHARS


def test_round_trips_when_cursor_encoded_and_decoded() -> None:
    cursor = Cursor(hwm=120, key=(1, "2026-10-09T14:00:00Z", None), id="session-17")

    text = encode_cursor(cursor)

    assert decode_cursor(text) == cursor
    assert len(text) <= MAX_CURSOR_CHARS
    assert "=" not in text
    assert set(text) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not base64 !!",
        _encoded(b"\xff\xfe"),
        _encoded(b"[1, 2]"),
        _encoded(b'{"h": -1, "k": [], "i": "x"}'),
        _encoded(b'{"h": 1, "k": [1.5], "i": "x"}'),
        _encoded(b'{"h": 1, "k": [], "i": "x", "extra": 1}'),
        "A" * (MAX_CURSOR_CHARS + 1),
    ],
)
def test_raises_invalid_cursor_when_text_is_invalid(text: str) -> None:
    with pytest.raises(InvalidCursorError) as raised:
        decode_cursor(text)

    assert isinstance(raised.value, AgentHubError)
    assert "cursor" in str(raised.value)


def test_refuses_to_encode_when_cursor_would_be_too_long() -> None:
    with pytest.raises(ValueError, match="cursor"):
        encode_cursor(Cursor(hwm=1, key=("x" * 600,), id="a"))
