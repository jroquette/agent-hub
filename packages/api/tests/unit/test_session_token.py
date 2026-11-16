import hmac
import string
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_hub.api.session_token import (
    MAX_TOKEN_CHARS,
    SessionToken,
    TokenFileError,
    cookie_name,
    mint_token,
    read_token_file,
    shared_cookie_name,
)

TOKEN = "synthetic-token-0123456789abcdefghijklmnopqrstuv"  # noqa: S105 -- synthetic
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


def _token_file(tmp_path: Path, content: str = TOKEN, mode: int = 0o600) -> Path:
    path = tmp_path / "launch-token"
    path.write_text(content, encoding="ascii")
    path.chmod(mode)
    return path


def test_reads_token_without_whitespace_when_token_file_private(tmp_path: Path) -> None:
    assert read_token_file(_token_file(tmp_path, f"{TOKEN}\n")) == TOKEN


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o620, 0o602])
def test_refuses_token_file_when_group_or_others_have_access(tmp_path: Path, mode: int) -> None:
    with pytest.raises(TokenFileError, match="private") as refused:
        read_token_file(_token_file(tmp_path, mode=mode))

    assert TOKEN not in str(refused.value)


def test_refuses_token_file_when_symlink(tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(_token_file(tmp_path))

    with pytest.raises(TokenFileError, match="regular file"):
        read_token_file(link)


def test_refuses_token_file_when_missing(tmp_path: Path) -> None:
    with pytest.raises(TokenFileError, match="cannot read"):
        read_token_file(tmp_path / "absent")


@pytest.mark.parametrize("content", ["", "  \n", "x" * (MAX_TOKEN_CHARS + 1), "not a token!"])
def test_refuses_token_file_when_content_no_url_safe_token(tmp_path: Path, content: str) -> None:
    with pytest.raises(TokenFileError, match="no url-safe token"):
        read_token_file(_token_file(tmp_path, content))


def test_names_shared_cookie_after_file_when_named(tmp_path: Path) -> None:
    path = _token_file(tmp_path)
    other = tmp_path / "other"

    name = shared_cookie_name(path)

    assert name == shared_cookie_name(tmp_path / "." / "launch-token")
    assert name != shared_cookie_name(other)
    assert name.startswith("agent_hub_")
    assert TOKEN not in name
