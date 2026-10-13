"""The per-launch token that opens the agent-session routes (P6, ADR 0027).

``hub web`` mints one token per start (``mint_token``) and prints it once in its URL; the
browser trades it for an ``HttpOnly`` cookie named after the port (``cookie_name``), since
cookies are not scoped by port. The token lives in memory only: never in a file, a log line or
a child's environment, and its ``repr`` hides it. Comparison is constant-time
(``hmac.compare_digest`` over UTF-8 bytes); a candidate longer than ``MAX_TOKEN_CHARS`` is
refused before it is compared.
"""

import hmac
import secrets
from dataclasses import dataclass, field

TOKEN_BYTES = 32
MAX_TOKEN_CHARS = 128
COOKIE_PREFIX = "agent_hub_"


def mint_token() -> str:
    """A fresh url-safe token (43 characters, 256 bits)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def cookie_name(port: int) -> str:
    """The cookie that carries the token for the server on ``port``."""
    return f"{COOKIE_PREFIX}{port}"


@dataclass(frozen=True)
class SessionToken:
    """The token of this launch; ``matches`` tells whether a candidate is it."""

    value: str = field(repr=False)

    def matches(self, candidate: str | None) -> bool:
        """Whether ``candidate`` is the token, compared in constant time."""
        if not candidate or len(candidate) > MAX_TOKEN_CHARS:
            return False
        return hmac.compare_digest(self.value.encode(), candidate.encode())
