"""Serve the app on 127.0.0.1 only (D2, D25): the socket is bound here, then given to uvicorn.

Binding first means a port in use is reported before anything starts, and uvicorn never picks
the address: there is no host option to get wrong.
"""

import errno
import socket

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
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Lets a restart reuse the port while old connections sit in TIME_WAIT; a live listener
    # still makes bind fail.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((LOOPBACK, port))
        sock.listen(socket.SOMAXCONN)
    except OSError as error:
        sock.close()
        if error.errno == errno.EADDRINUSE:
            raise PortInUseError(port) from None
        raise
    sock.set_inheritable(True)
    return sock


class LoopbackServer:
    """uvicorn on a socket bound by ``bind_loopback``: no access log (it would print query
    strings), no proxy headers trusted, no server header."""

    def __init__(self, app: FastAPI, sock: socket.socket) -> None:
        self._sock = sock
        config = uvicorn.Config(
            app,
            log_config=None,
            access_log=False,
            proxy_headers=False,
            server_header=False,
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        )
        self._server = uvicorn.Server(config)

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
        """Ask a running server to finish."""
        self._server.should_exit = True


def serve_on(app: FastAPI, sock: socket.socket) -> None:
    """Serve ``app`` on ``sock`` until interrupted."""
    LoopbackServer(app, sock).run()
