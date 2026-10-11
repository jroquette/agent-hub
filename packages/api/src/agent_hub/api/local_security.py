"""The local server's request checks (D25): a pure ASGI middleware in front of every route.

The server binds 127.0.0.1 only, but a page on any site can still make the browser send it a
request. So: the ``Host`` must name the loopback at this port (DNS rebinding), a ``POST`` or
``DELETE`` carrying an ``Origin`` must come from this origin (cross-site writes), bodies stop at
1 MiB, API answers are never cached, a CSP keeps the app to its own origin, and no CORS header
is ever sent.
"""

from collections.abc import Iterable

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.rfc9457 import BodyTooLargeError, problem
from agent_hub.core.ingestion.hook_envelope import MAX_BODY_BYTES

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "font-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def allowed_hosts(port: int) -> frozenset[str]:
    """The ``Host`` values this server answers: a loopback name with its port."""
    return frozenset(f"{host}:{port}" for host in LOOPBACK_HOSTS)


def allowed_origins(port: int) -> frozenset[str]:
    """The origins of this server, as a browser sends them in ``Origin``."""
    return frozenset(f"http://{host}" for host in allowed_hosts(port))


class LocalSecurityMiddleware:
    """Refuses foreign hosts, cross-origin writes and large bodies; adds the security headers."""

    def __init__(self, app: ASGIApp, *, port: int, max_body_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self._hosts = allowed_hosts(port)
        self._origins = allowed_origins(port)
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        refusal = self._refusal(scope)
        if refusal is not None:
            status, title, detail = refusal
            response = problem(status, title=title, detail=detail, instance=scope["path"])
            await response(scope, receive, _with_headers(send, scope))
            return
        await self._serve_capped(scope, receive, send)

    def _refusal(self, scope: Scope) -> tuple[int, str, str] | None:
        headers = Headers(scope=scope)
        if headers.get("host") not in self._hosts:
            return 403, "Forbidden host", "This server answers only on its loopback address."
        origin = headers.get("origin")
        if (
            scope["method"] in STATE_CHANGING_METHODS
            and origin is not None
            and origin not in self._origins
        ):
            return 403, "Forbidden origin", "Changes are accepted only from this server's pages."
        length = headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > self._max_body_bytes):
            return 413, "Request body too large", self._too_large_detail()
        return None

    def _too_large_detail(self) -> str:
        return f"Request bodies are limited to {self._max_body_bytes} bytes."

    async def _serve_capped(self, scope: Scope, receive: Receive, send: Send) -> None:
        received = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_body_bytes:
                    raise BodyTooLargeError(self._max_body_bytes)
            return message

        secured_send = _with_headers(send, scope)

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await secured_send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BodyTooLargeError:
            if started:
                raise
            response = problem(
                413,
                title="Request body too large",
                detail=self._too_large_detail(),
                instance=scope["path"],
            )
            await response(scope, receive, secured_send)


def _with_headers(send: Send, scope: Scope) -> Send:
    is_api = str(scope["path"]).startswith(f"{API_PREFIX}/") or scope["path"] == API_PREFIX

    async def send_with_headers(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = MutableHeaders(scope=message)
            _drop_cors(headers, list(headers.keys()))
            for name, value in SECURITY_HEADERS.items():
                headers[name] = value
            if is_api:
                headers["Cache-Control"] = "no-store"
        await send(message)

    return send_with_headers


def _drop_cors(headers: MutableHeaders, names: Iterable[str]) -> None:
    for name in names:
        if name.lower().startswith("access-control-"):
            del headers[name]
