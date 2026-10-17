"""The local server's request checks (D25): a pure ASGI middleware in front of every route.

The server binds 127.0.0.1 only, but a page on any site can still make the browser send it a
request. So: the ``Host`` must name the loopback at this port (DNS rebinding), a ``POST`` or
``DELETE`` carrying an ``Origin`` must come from this origin (cross-site writes), the learning
actions, the workflow-run writes and a workflow gate's decision also need that ``Origin``, a
same-origin fetch and a JSON body (S7), so do the hub registry writes (``POST /hubs``, ``DELETE
/hubs/{id}``; a missing ``Origin`` is refused too, A11: a registered hub is a folder sessions
may start in), bodies stop at 1 MiB (8 MiB for ``POST /agent-sessions``, which may carry a
screenshot), API answers are never cached, a CSP keeps the app to its own origin, and no CORS
header is ever sent. No route speaks WebSocket (ADR 0031, D3): any ``websocket`` scope is
closed with 1008 before it is accepted, so an upgrade never skips these checks (P7, AC-165.54).

``AGENT_HUB_ALLOWED_HOSTS`` (read by ``hub web``, parsed here) may add exact ``host[:port]``
names, for example the host port a container publishes; never a wildcard.
"""

import ipaddress
import re
from collections.abc import Iterable
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.rfc9457 import BodyTooLargeError, problem
from agent_hub.core.ingestion.hook_envelope import MAX_BODY_BYTES

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# The writes that open a hub pull request (S7): besides the checks above, they need this
# server's own ``Origin``, a same-origin fetch (when the browser says) and a JSON body, which a
# cross-site form cannot send without a preflight that is never granted. Other writes keep the
# checks above only (E9).
# The workflow-run writes (AC-213.19) start or stop a child process: strict too, and they need
# the launch's cookie when sessions are on (``session_access``). A workflow gate's decision
# (AC-213.18) runs the CLI and resumes the run, so it is one of them.
RUN_WRITES = re.compile(
    rf"^{re.escape(API_PREFIX)}/(workflow-runs(/[^/]+/(cancel|resume|abandon))?"
    r"|approvals/[^/]+/decision)$"
)
STRICT_WRITES = re.compile(
    rf"^{re.escape(API_PREFIX)}/learnings/[^/]+/(accept|reject)$|{RUN_WRITES.pattern}"
)
# The hub registry writes (A11): this server's exact ``Origin`` is required, a missing one too.
# A script (``make connect``, the demo seed) sends its base URL as ``Origin``.
HUB_REGISTRY_WRITES = (
    ("POST", re.compile(rf"^{re.escape(API_PREFIX)}/hubs$")),
    ("DELETE", re.compile(rf"^{re.escape(API_PREFIX)}/hubs/[^/]+$")),
    # Rewrites the hub's pin and runs ``hub sync`` in it.
    ("POST", re.compile(rf"^{re.escape(API_PREFIX)}/hubs/[^/]+/platform-sync$")),
)
# The routes with a larger body cap: a session's first prompt may carry a PNG screenshot (at
# most ``MAX_SCREENSHOT_BYTES`` decoded, 5 MiB of base64), and a later message up to
# ``MAX_MESSAGE_SCREENSHOTS`` of them; either one also carries a text of up to the largest
# ``--message-max-bytes`` (4 MiB), which JSON escaping may grow. Every other route keeps
# ``max_body_bytes``.
AGENT_SESSION_CREATE_BODY_BYTES: Final = 16 * 1024 * 1024
AGENT_SESSION_CREATE_PATH: Final = f"{API_PREFIX}/agent-sessions"
AGENT_SESSION_MESSAGE_BODY_BYTES: Final = 64 * 1024 * 1024
AGENT_SESSION_MESSAGE_PATH: Final = re.compile(
    rf"^{re.escape(API_PREFIX)}/agent-sessions/[^/]+/messages$"
)
JSON_MEDIA_TYPE = "application/json"
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


# The close code of a refused WebSocket upgrade (RFC 6455, "policy violation").
WEBSOCKET_POLICY_VIOLATION = 1008

ALLOWED_HOSTS_VARIABLE = "AGENT_HUB_ALLOWED_HOSTS"
# A DNS name (letters, digits, hyphens, dots; no label starts with a hyphen) or a bracketed
# IPv6 address, then an optional port. Anything else, a wildcard included, is refused.
_HOST_ENTRY = re.compile(
    r"(?P<host>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*"
    r"|\[[0-9a-f:.]+\])(?::(?P<port>[0-9]{1,5}))?"
)
MAX_PORT = 65_535


def allowed_hosts(port: int, *, extra: Iterable[str] = ()) -> frozenset[str]:
    """The ``Host`` values this server answers: a loopback name with its port, plus ``extra``
    (exact ``host:port`` values, from ``parse_allowed_hosts``)."""
    return frozenset({*(f"{host}:{port}" for host in LOOPBACK_HOSTS), *extra})


def allowed_origins(port: int, *, extra: Iterable[str] = ()) -> frozenset[str]:
    """The origins of this server, as a browser sends them in ``Origin``."""
    return frozenset(f"http://{host}" for host in allowed_hosts(port, extra=extra))


def parse_allowed_hosts(value: str, *, port: int) -> frozenset[str]:
    """The ``host:port`` names of a comma list of ``host[:port]`` (the server's port when none).

    Names are lowercased; empty entries are skipped. ``ValueError`` naming the variable for an
    entry that is not a plain host and port, such as ``*``, a URL or a path.
    """
    names: set[str] = set()
    for raw in value.split(","):
        entry = raw.strip().lower()
        if entry:
            names.add(_host_and_port(entry, default_port=port))
    return frozenset(names)


def _host_and_port(entry: str, *, default_port: int) -> str:
    matched = _HOST_ENTRY.fullmatch(entry)
    problem = f"{ALLOWED_HOSTS_VARIABLE}: {entry!r} is not host[:port]"
    if matched is None:
        raise ValueError(problem)
    host, port_text = matched["host"], matched["port"]
    if host.startswith("["):
        try:
            ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            raise ValueError(problem) from None
    port = default_port if port_text is None else int(port_text)
    if not 1 <= port <= MAX_PORT:
        raise ValueError(problem)
    return f"{host}:{port}"


def is_strict_write(method: str, path: str) -> bool:
    """Whether a request is one of the writes that take the strict checks (``STRICT_WRITES``)."""
    return method in STATE_CHANGING_METHODS and STRICT_WRITES.fullmatch(path) is not None


def is_run_write(method: str, path: str) -> bool:
    """Whether a request starts, cancels, resumes or abandons a workflow run, or decides one's
    gate (``RUN_WRITES``)."""
    return method in STATE_CHANGING_METHODS and RUN_WRITES.fullmatch(path) is not None


def is_hub_registry_write(method: str, path: str) -> bool:
    """Whether a request registers or removes a hub (``HUB_REGISTRY_WRITES``)."""
    return any(
        method == written and pattern.fullmatch(path) is not None
        for written, pattern in HUB_REGISTRY_WRITES
    )


def is_json_media_type(content_type: str | None) -> bool:
    """Whether a ``Content-Type`` names ``application/json``, parameters (a charset) aside."""
    if content_type is None:
        return False
    return content_type.split(";", 1)[0].strip().lower() == JSON_MEDIA_TYPE


def strict_refusal(headers: Headers, *, needs_json: bool = True) -> tuple[int, str, str] | None:
    """Why a strict write is refused (status, title, detail), or None: its ``Origin`` must be
    this server's own (the ``Host`` was checked first), ``Sec-Fetch-Site`` same-origin when
    sent, and, when ``needs_json``, its body ``application/json`` (else 415)."""
    if headers.get("origin") != f"http://{headers.get('host')}":
        return 403, "Forbidden origin", "This change is accepted only from this server's pages."
    site = headers.get("sec-fetch-site")
    if site is not None and site != "same-origin":
        return 403, "Forbidden fetch site", "This change is accepted only from this server's pages."
    if needs_json and not is_json_media_type(headers.get("content-type")):
        return 415, "Unsupported media type", f"The body must be {JSON_MEDIA_TYPE}."
    return None


class LocalSecurityMiddleware:
    """Refuses foreign hosts, cross-origin writes and large bodies; adds the security headers."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        port: int,
        extra_hosts: Iterable[str] = (),
        max_body_bytes: int = MAX_BODY_BYTES,
    ) -> None:
        self.app = app
        self._hosts = allowed_hosts(port, extra=extra_hosts)
        self._origins = allowed_origins(port, extra=extra_hosts)
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": WEBSOCKET_POLICY_VIOLATION})
            return
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
        if is_strict_write(scope["method"], scope["path"]):
            strict = strict_refusal(headers)
            if strict is not None:
                return strict
        if is_hub_registry_write(scope["method"], scope["path"]):
            strict = strict_refusal(headers, needs_json=scope["method"] == "POST")
            if strict is not None:
                return strict
        length = headers.get("content-length")
        cap = self._body_cap(scope)
        if length is not None and (not length.isdigit() or int(length) > cap):
            return 413, "Request body too large", _too_large_detail(cap)
        return None

    def _body_cap(self, scope: Scope) -> int:
        if scope["method"] == "POST" and scope["path"] == AGENT_SESSION_CREATE_PATH:
            return AGENT_SESSION_CREATE_BODY_BYTES
        if scope["method"] == "POST" and AGENT_SESSION_MESSAGE_PATH.match(scope["path"]):
            return AGENT_SESSION_MESSAGE_BODY_BYTES
        return self._max_body_bytes

    async def _serve_capped(self, scope: Scope, receive: Receive, send: Send) -> None:
        received = 0
        started = False
        cap = self._body_cap(scope)

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > cap:
                    raise BodyTooLargeError(cap)
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
                detail=_too_large_detail(cap),
                instance=scope["path"],
            )
            await response(scope, receive, secured_send)


def _too_large_detail(cap: int) -> str:
    return f"Request bodies are limited to {cap} bytes."


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
