import hmac
import string
from unittest.mock import patch

import pytest

from agent_hub.api.session_token import (
    MAX_TOKEN_CHARS,
    SessionToken,
    cookie_name,
    mint_token,
)

TOKEN = "synthetic-token-0123456789abcdefghijklmnopqrstuv"
URL_SAFE = frozenset(string.ascii_letters + string.digits + "-_")


def test_refuses_token_when_last_character_differs() -> None:
    other = TOKEN[:-1] + ("w" if TOKEN[-1] != "w" else "x")

    assert SessionToken(TOKEN).matches(other) is False


def test_uses_compare_digest_when_matching() -> None:
    with patch(
        "agent_hub.api.session_token.hmac.compare_digest", wraps=hmac.compare_digest
    ) as compare:
        matched = SessionToken(TOKEN).matches(TOKEN)

    assert matched is True
    compare.assert_called_once_with(TOKEN.encode(), TOKEN.encode())


@pytest.mark.parametrize("candidate", [None, "", "x" * (MAX_TOKEN_CHARS + 1), "é" + TOKEN[1:]])
def test_refuses_token_when_missing_empty_too_long_or_other_text(candidate: str | None) -> None:
    assert SessionToken(TOKEN).matches(candidate) is False


def test_hides_value_when_token_shown() -> None:
    token = SessionToken(TOKEN)

    assert TOKEN not in repr(token)
    assert TOKEN not in str(token)


def test_mints_url_safe_token_of_43_characters_when_minted() -> None:
    first, second = mint_token(), mint_token()

    assert len(first) >= 43
    assert set(first) <= URL_SAFE
    assert first != second


def test_names_cookie_after_port_when_named() -> None:
    assert cookie_name(7420) == "agent_hub_7420"
