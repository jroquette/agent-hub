"""The per-launch token that opens the agent-session routes (P6, ADR 0031).

``hub web`` mints one token per start (``mint_token``) and prints it once in its URL; the
browser trades it for an ``HttpOnly`` cookie named after the port (``cookie_name``), since
cookies are not scoped by port. The token lives in memory only: never in a file, a log line or
a child's environment, and its ``repr`` hides it. Comparison is constant-time
(``hmac.compare_digest`` over UTF-8 bytes); a candidate longer than ``MAX_TOKEN_CHARS`` is
refused before it is compared.

Two servers of one launch (the playground's conductor and its live API, which restarts) share
one token through a file only this user can read (``read_token_file``) and one cookie named
after that file (``shared_cookie_name``), so the browser's cookie opens both and survives a
restart.
"""

import hashlib
import hmac
import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

TOKEN_BYTES = 32
MAX_TOKEN_CHARS = 128
COOKIE_PREFIX = "agent_hub_"


def mint_token() -> str:
    """A fresh url-safe token (43 characters, 256 bits)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def cookie_name(port: int) -> str:
    """The cookie that carries the token for the server on ``port``."""
    return f"{COOKIE_PREFIX}{port}"


def shared_cookie_name(token_file: Path) -> str:
    """The cookie of every server that reads its token from ``token_file``: named after the
    file's real path, never after the token."""
    digest = hashlib.sha256(str(token_file.resolve()).encode()).hexdigest()[:12]
    return f"{COOKIE_PREFIX}{digest}"


class TokenFileError(ValueError):
    """A token file that cannot be used: unreadable, not private, or not a token."""


def read_token_file(token_file: Path) -> str:
    """The token in ``token_file``, surrounding whitespace dropped.

    Refused (``TokenFileError``): a symlink, a file another user owns or that the group or
    others may read or write, and a value that is empty, longer than ``MAX_TOKEN_CHARS`` or
    not url-safe. The message never holds the file's content.
    """
    try:
        info = token_file.lstat()
    except OSError as error:
        raise TokenFileError(f"cannot read {token_file}: {error.strerror or error}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise TokenFileError(f"{token_file} is not a regular file")
    if info.st_uid != os.getuid() or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise TokenFileError(f"{token_file} must be yours and private (chmod 600)")
    try:
        value = token_file.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise TokenFileError(f"cannot read {token_file} as a token") from error
    if not value or len(value) > MAX_TOKEN_CHARS or not _URL_SAFE.issuperset(value):
        raise TokenFileError(f"{token_file} holds no url-safe token")
    return value


_URL_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


@dataclass(frozen=True)
class SessionToken:
    """The token of this launch; ``matches`` tells whether a candidate is it."""

    value: str = field(repr=False)

    def matches(self, candidate: str | None) -> bool:
        """Whether ``candidate`` is the token, compared in constant time."""
        if not candidate or len(candidate) > MAX_TOKEN_CHARS:
            return False
        return hmac.compare_digest(self.value.encode(), candidate.encode())
