"""Serve the app on 127.0.0.1 (D2, D25): the socket is bound here, then given to uvicorn.

Binding first means a port in use is reported before anything starts, and uvicorn never picks
the address. ``hub web`` decides which address may be bound (loopback, or any address only
inside the agent-hub container, ADR 0022); this module binds what it is given.
"""

import errno
import logging
import socket
from collections.abc import Callable
from types import FrameType

import uvicorn
from fastapi import FastAPI

from agent_hub.core.errors import AgentHubError

LOOPBACK = "127.0.0.1"
# Open streams get this long to finish when the server stops (an SSE stream never does).
GRACEFUL_SHUTDOWN_SECONDS = 2


class PortInUseError(AgentHubError):
    """Another process listens on the port."""

    def __init__(self, port: int) -> None:
        self.port = port
        super().__init__(f"port {port} is in use")


def bind_loopback(port: int) -> socket.socket:
    """A listening socket on ``127.0.0.1:port`` (0 picks a free port).

    ``PortInUseError`` when the port is taken; any other ``OSError`` propagates.
    """
    return bind_address(LOOPBACK, port)


def bind_address(host: str, port: int) -> socket.socket:
    """A listening socket on ``host:port``, ``host`` an IPv4 or IPv6 address (0 picks a port).

    ``PortInUseError`` when the port is taken; any other ``OSError`` propagates.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    # Lets a restart reuse the port while old connections sit in TIME_WAIT; a live listener
    # still makes bind fail.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(socket.SOMAXCONN)
    except OSError as error:
        sock.close()
        if error.errno == errno.EADDRINUSE:
            raise PortInUseError(port) from None
        raise
    sock.set_inheritable(True)
    return sock


type ExitHook = Callable[[], None]

_log = logging.getLogger(__name__)


def _call(hook: ExitHook | None) -> None:
    if hook is None:
        return
    try:
        hook()
    except Exception:  # noqa: BLE001 -- the server stops whatever the hook does
        _log.warning("exit hook failed", exc_info=True)


class _HookedServer(uvicorn.Server):
    """uvicorn's server, calling ``on_exit`` on the first SIGINT or SIGTERM, before it starts
    to stop (and so before the graceful wait)."""

    def __init__(self, config: uvicorn.Config, on_exit: ExitHook | None) -> None:
        super().__init__(config)
        self._on_exit = on_exit

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if not self.should_exit:
            _call(self._on_exit)
        super().handle_exit(sig, frame)


def app_exit_hook(app: FastAPI) -> ExitHook | None:
    """The hook ``create_app`` keeps on ``app.state.on_exit``, if any."""
    hook = getattr(app.state, "on_exit", None)
    return hook if callable(hook) else None


class LoopbackServer:
    """uvicorn on a socket bound by ``bind_loopback``: no access log (it would print query
    strings), no proxy headers trusted, no server header.

    ``on_exit`` (default: the app's own hook, ``app.state.on_exit``) is called once when the
    server is told to stop, by a signal or ``stop``, before the graceful wait (P12): the
    agent sessions start ending and their streams close at once."""

    def __init__(
        self, app: FastAPI, sock: socket.socket, *, on_exit: ExitHook | None = None
    ) -> None:
        self._sock = sock
        self._on_exit = on_exit if on_exit is not None else app_exit_hook(app)
        config = uvicorn.Config(
            app,
            log_config=None,
            access_log=False,
            proxy_headers=False,
            server_header=False,
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        )
        self._server = _HookedServer(config, self._on_exit)

    @property
    def started(self) -> bool:
        """Whether the server accepts requests."""
        return bool(self._server.started)

    def run(self) -> None:
        """Serve until stopped or interrupted; the socket is closed afterwards."""
        try:
            self._server.run(sockets=[self._sock])
        finally:
            self._sock.close()

    def stop(self) -> None:
        """Ask a running server to finish (the exit hook runs first, once)."""
        if not self._server.should_exit:
            _call(self._on_exit)
        self._server.should_exit = True

    def signal(self, sig: int) -> None:
        """Handle ``sig`` as the server's signal handler does (SIGINT, SIGTERM)."""
        self._server.handle_exit(sig, None)


def serve_on(app: FastAPI, sock: socket.socket, *, on_exit: ExitHook | None = None) -> None:
    """Serve ``app`` on ``sock`` until interrupted; ``on_exit`` as ``LoopbackServer``'s."""
    LoopbackServer(app, sock, on_exit=on_exit).run()
