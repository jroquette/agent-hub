"""Who may reach the agent-session routes (P6, L1, L2; ADR 0027): a pure ASGI middleware.

It sits inside ``LocalSecurityMiddleware``, so the ``Host`` is already this server's, and it
refuses before routing, so a refused request never reaches a port.

- **Exchange.** A ``GET`` or ``HEAD`` outside ``/api`` with a ``token`` query answers 303 to the
  same path with the other query parameters; when the token is this launch's, it also sets the
  cookie ``agent_hub_<port>`` (``HttpOnly; SameSite=Strict; Path=/``). The redirect drops the
  token, so it is one hop, never a loop, and the token leaves the address bar.
- **Off.** With ``sessions_off`` (the container, L2) every route under ``/api/v1/agent-sessions``
  answers 404 ``agent-sessions-off``, cookie or not.
- **Cookie.** Every route under the prefix needs the cookie (constant-time match); else 401.
  With no token configured, nothing matches.
- **Writes** need this server's exact ``Origin``, ``Sec-Fetch-Site: same-origin`` when sent and,
  except ``DELETE`` (which carries no body), a JSON body (403, 415).
- **Reads** (the stream included) refuse any ``Origin`` other than this server's and a
  ``Sec-Fetch-Site`` of ``cross-site`` or ``same-site``: another port on the loopback is
  same-site and carries the Strict cookie (spike, L1). A missing ``Origin`` passes.

The token, the cookie and the query string are never logged or echoed in a problem.
"""

from urllib.parse import parse_qsl, quote, urlencode

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from agent_hub.api.local_security import STATE_CHANGING_METHODS, strict_refusal
from agent_hub.api.openapi_paths import AGENT_SESSIONS, API_PREFIX
from agent_hub.api.rfc9457 import problem
from agent_hub.api.session_token import SessionToken, cookie_name

TOKEN_PARAMETER = "token"  # noqa: S105 -- the query parameter's name, not a token
OFF_PROBLEM_TYPE = "urn:agent-hub:problem:agent-sessions-off"
UNAUTHORIZED_PROBLEM_TYPE = "urn:agent-hub:problem:agent-session-unauthorized"
EXCHANGE_METHODS = frozenset({"GET", "HEAD"})
BODILESS_WRITES = frozenset({"DELETE"})
# What a browser sends for a request this server's own page (or the address bar) made.
OWN_FETCH_SITES = frozenset({"same-origin", "none"})
# Characters a redirect path keeps as they are; the rest (a backslash among them) is encoded.
_PATH_SAFE = "/:@!$&'()*+,;=-._~%"


def is_agent_session_path(path: str) -> bool:
    """Whether ``path`` is under ``/api/v1/agent-sessions``."""
    return path == AGENT_SESSIONS or path.startswith(f"{AGENT_SESSIONS}/")


def _is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(f"{API_PREFIX}/")


def exchange_location(path: str, query_string: bytes) -> str:
    """Where the exchange redirects: ``path`` on this server, without the ``token`` parameter.

    Leading slashes collapse to one and unsafe characters are percent-encoded, so the
    location can never name another host (``//host`` or ``/\\host``).
    """
    location = "/" + quote(path.lstrip("/"), safe=_PATH_SAFE)
    kept = [
        (name, value)
        for name, value in parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)
        if name != TOKEN_PARAMETER
    ]
    return f"{location}?{urlencode(kept)}" if kept else location


def session_cookie(name: str, token: str) -> str:
    """The ``Set-Cookie`` value of the exchange."""
    return f"{name}={token}; HttpOnly; SameSite=Strict; Path=/"


def read_refusal(headers: Headers) -> tuple[int, str, str] | None:
    """Why a read under the prefix is refused (L1), or None."""
    origin = headers.get("origin")
    if origin is not None and origin != f"http://{headers.get('host')}":
        return 403, "Forbidden origin", "Agent sessions are read only from this server's pages."
    site = headers.get("sec-fetch-site")
    if site is not None and site not in OWN_FETCH_SITES:
        return 403, "Forbidden fetch site", "Agent sessions are read only from this server's pages."
    return None


class SessionAccessMiddleware:
    """The token exchange, and the cookie and Origin rules of the agent-session routes."""

    def __init__(
        self, app: ASGIApp, *, port: int, token: str | None, sessions_off: bool = False
    ) -> None:
        self.app = app
        self._cookie = cookie_name(port)
        self._token = SessionToken(token) if token else None
        self._off = sessions_off

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope["path"])
        headers = Headers(scope=scope)
        if is_agent_session_path(path):
            response = self._refusal(scope, headers)
        else:
            response = self._exchange(scope)
        if response is None:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)

    def _exchange(self, scope: Scope) -> Response | None:
        query: bytes = scope.get("query_string", b"")
        if scope["method"] not in EXCHANGE_METHODS or _is_api_path(str(scope["path"])):
            return None
        pairs = parse_qsl(query.decode("latin-1"), keep_blank_values=True)
        candidates = [value for name, value in pairs if name == TOKEN_PARAMETER]
        if not candidates:
            return None
        candidate = candidates[0]
        response = Response(
            status_code=303,
            headers={"Location": exchange_location(str(scope["path"]), query)},
        )
        if self._token is not None and self._token.matches(candidate):
            response.headers["Set-Cookie"] = session_cookie(self._cookie, self._token.value)
        return response

    def _refusal(self, scope: Scope, headers: Headers) -> Response | None:
        instance = str(scope["path"])
        if self._off:
            return problem(
                404,
                title="Agent sessions are off",
                detail="Agent sessions cannot be driven from the agent-hub container.",
                instance=instance,
                members={"type": OFF_PROBLEM_TYPE},
            )
        if not self._has_cookie(headers):
            response = problem(
                401,
                title="Session cookie required",
                detail="Open the address hub web printed (with its token) to drive sessions.",
                instance=instance,
                members={"type": UNAUTHORIZED_PROBLEM_TYPE},
            )
            response.headers["WWW-Authenticate"] = 'Cookie realm="agent-hub"'
            return response
        method = str(scope["method"])
        if method in STATE_CHANGING_METHODS:
            refusal = strict_refusal(headers, needs_json=method not in BODILESS_WRITES)
        else:
            refusal = read_refusal(headers)
        if refusal is None:
            return None
        status, title, detail = refusal
        return problem(status, title=title, detail=detail, instance=instance)

    def _has_cookie(self, headers: Headers) -> bool:
        if self._token is None:
            return False
        cookies = cookie_parser(headers.get("cookie", ""))
        return self._token.matches(cookies.get(self._cookie))
