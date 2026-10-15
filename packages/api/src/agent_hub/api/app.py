"""``create_app``: the FastAPI application of ``hub web``."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI

from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.json_logging import RequestLogMiddleware
from agent_hub.api.local_security import LocalSecurityMiddleware
from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.rfc9457 import ProblemFactory, UnhandledErrorMiddleware, install_problem_handlers
from agent_hub.api.routes import (
    agent_session_stream,
    agent_sessions,
    approvals,
    cloud_sessions,
    collector,
    doctor,
    features,
    hooks,
    hubs,
    learnings,
    live,
    overview,
    projects,
    runs,
    sessions,
    settings,
    skills,
    streams,
    workflows,
)
from agent_hub.api.session_access import SessionAccessMiddleware
from agent_hub.api.settings import ApiSettings
from agent_hub.api.static_files import WEB_DIST, WebApp

# The document's version is the API package's, not the running hub's: the committed
# openapi.json must not change with each CLI release.
DISTRIBUTION = "agent-hub-api"
ROUTERS = (
    hooks,
    hubs,
    projects,
    skills,
    overview,
    sessions,
    live,
    runs,
    workflows,
    approvals,
    learnings,
    features,
    doctor,
    collector,
    settings,
    streams,
    # Cloud first, then the static agent-session paths before the id ones (P5).
    cloud_sessions,
    agent_sessions,
    agent_session_stream,
)


class AppLifecycle(Protocol):
    """What runs beside the routes while the app serves (the agent sessions' sweep and
    shutdown, ``SessionRuntime``)."""

    async def start(self) -> None:
        """Called once the app starts, before the first request."""
        ...

    def begin_exit(self) -> None:
        """Called from the server's signal handler, before its graceful wait; must not block."""
        ...

    async def stop(self) -> None:
        """Called when the app shuts down; returns once everything it started has ended."""
        ...


class _Serving:
    """The app's start, signal hook and stop: the change feed and the lifecycle."""

    def __init__(self, ports: ApiPorts, lifecycle: AppLifecycle | None) -> None:
        self._ports = ports
        self._lifecycle = lifecycle

    def _close_feed(self) -> None:
        if self._ports.change_feed is not None:
            self._ports.change_feed.close()

    def on_exit(self) -> None:
        """Close the change feed and begin the lifecycle's exit (the server's signal hook)."""
        self._close_feed()
        if self._lifecycle is not None:
            self._lifecycle.begin_exit()

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        """Start the lifecycle; on shutdown close the feed and wait for the lifecycle."""
        if self._lifecycle is not None:
            await self._lifecycle.start()
        try:
            yield
        finally:
            self._close_feed()
            if self._lifecycle is not None:
                await self._lifecycle.stop()


def create_app(
    api_settings: ApiSettings,
    *,
    ports: ApiPorts | None = None,
    problems: Mapping[type[Exception], ProblemFactory] | None = None,
    web_dist: Path = WEB_DIST,
    lifecycle: AppLifecycle | None = None,
) -> FastAPI:
    """The app with every Phase 2 route under ``/api/v1`` and the web app at ``/``.

    ``ports`` are the adapters the routes use (a route whose port is None answers 501);
    ``problems`` adds error mappings for exceptions of the wired adapters. No docs pages are
    served. Requests pass, outermost first: the request log, the 500 guard, the local
    security checks, the agent-session access checks (token exchange, cookie), then the
    routes. ``lifecycle`` starts with the app and stops with it. On shutdown the change feed
    is closed, so open streams end; ``app.state.on_exit`` (the server's signal hook) closes it
    and begins the lifecycle's exit at once, before the server's graceful wait.
    """
    ports = ports or ApiPorts()
    serving = _Serving(ports, lifecycle)

    app = FastAPI(
        title="agent-hub",
        version=version(DISTRIBUTION),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=serving.lifespan,
    )
    app.state.settings = api_settings
    app.state.ports = ports
    app.state.on_exit = serving.on_exit
    install_problem_handlers(app, extra=problems)
    for module in ROUTERS:
        app.include_router(module.router, prefix=API_PREFIX)
    # The web app answers what no route matches; a mount would also swallow a wrong method
    # on an API path, which must stay a 405.
    app.router.default = WebApp(web_dist)
    # add_middleware puts each new one outside the previous ones.
    app.add_middleware(
        SessionAccessMiddleware,
        port=api_settings.port,
        token=api_settings.session_token,
        sessions_off=api_settings.sessions_off,
    )
    app.add_middleware(
        LocalSecurityMiddleware, port=api_settings.port, extra_hosts=api_settings.allowed_hosts
    )
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestLogMiddleware)
    return app
