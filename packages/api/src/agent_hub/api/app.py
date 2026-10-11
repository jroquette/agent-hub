"""``create_app``: the FastAPI application of ``hub web``."""

from importlib.metadata import version

from fastapi import FastAPI

from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.rfc9457 import install_problem_handlers
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


def create_app(api_settings: ApiSettings) -> FastAPI:
    """The app with every Phase 2 route under ``/api/v1``; no docs pages are served."""
    app = FastAPI(
        title="agent-hub",
        version=version(DISTRIBUTION),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = api_settings
    install_problem_handlers(app)
    for module in ROUTERS:
        app.include_router(module.router, prefix=API_PREFIX)
    return app
