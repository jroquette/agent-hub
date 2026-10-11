"""``create_app``: the FastAPI application of ``hub web``."""

from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI

from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.json_logging import RequestLogMiddleware
from agent_hub.api.local_security import LocalSecurityMiddleware
from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.rfc9457 import ProblemFactory, UnhandledErrorMiddleware, install_problem_handlers
from agent_hub.api.routes import (
    approvals,
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
    streams,
)
from agent_hub.api.settings import ApiSettings
from agent_hub.api.static_files import WEB_DIST, WebApp

# The document's version is the API package's, not the running hub's: the committed
# openapi.json must not change with each CLI release.
DISTRIBUTION = "agent-hub-api"
ROUTERS = (
    hooks,
    hubs,
    projects,
    overview,
    sessions,
    live,
    runs,
    approvals,
    learnings,
    features,
    doctor,
    collector,
    settings,
    streams,
)


def create_app(
    api_settings: ApiSettings,
    *,
    ports: ApiPorts | None = None,
    problems: Mapping[type[Exception], ProblemFactory] | None = None,
    web_dist: Path = WEB_DIST,
) -> FastAPI:
    """The app with every Phase 2 route under ``/api/v1`` and the web app at ``/``.

    ``ports`` are the adapters the routes use (a route whose port is None answers 501);
    ``problems`` adds error mappings for exceptions of the wired adapters. No docs pages are
    served. Requests pass, outermost first: the request log, the 500 guard, the local
    security checks, then the routes.
    """
    app = FastAPI(
        title="agent-hub",
        version=version(DISTRIBUTION),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = api_settings
    app.state.ports = ports or ApiPorts()
    install_problem_handlers(app, extra=problems)
    for module in ROUTERS:
        app.include_router(module.router, prefix=API_PREFIX)
    # The web app answers what no route matches; a mount would also swallow a wrong method
    # on an API path, which must stay a 405.
    app.router.default = WebApp(web_dist)
    # add_middleware puts each new one outside the previous ones.
    app.add_middleware(LocalSecurityMiddleware, port=api_settings.port)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestLogMiddleware)
    return app
