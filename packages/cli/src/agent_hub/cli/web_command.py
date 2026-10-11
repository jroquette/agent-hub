"""``hub web``: serve the control plane's API and web app on 127.0.0.1 (D2).

The only cli module that imports ``agent_hub.api`` (import contract, erratum E1).
"""

import os
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from agent_hub.api.app import create_app
from agent_hub.api.json_logging import configure_logging
from agent_hub.api.server import LOOPBACK, PortInUseError, bind_loopback, serve_on
from agent_hub.api.settings import DEFAULT_PORT, ApiSettings
from agent_hub.cli.command_exits import fail
from agent_hub.cli.database_path import account_home_directory, default_database_path
from agent_hub.cli.errors import CliError, HomeDirectoryNotFoundError

REGISTRY_DIR = "agent-hub"
REGISTRY_FILE = "hubs.json"


def default_registry_path(environ: Mapping[str, str]) -> Path:
    """``$XDG_CONFIG_HOME/agent-hub/hubs.json``, else ``~/.config/agent-hub/hubs.json`` (D18).

    ``XDG_CONFIG_HOME`` counts only when absolute; the home directory is found as for the
    event database (``HOME`` when absolute, else the account's home).
    """
    config_home = environ.get("XDG_CONFIG_HOME", "")
    if config_home and Path(config_home).is_absolute():
        return Path(config_home) / REGISTRY_DIR / REGISTRY_FILE
    for home in (environ.get("HOME", ""), account_home_directory() or ""):
        if home and Path(home).is_absolute():
            return Path(home) / ".config" / REGISTRY_DIR / REGISTRY_FILE
    raise HomeDirectoryNotFoundError


def web(
    *,
    port: Annotated[
        int,
        typer.Option("--port", min=1, max=65535, help="Port on 127.0.0.1 to listen on."),
    ] = DEFAULT_PORT,
    db: Annotated[
        Path | None,
        typer.Option(
            "--db",
            envvar="AGENT_HUB_DB",
            help=(
                "Event database file. Default: $XDG_DATA_HOME/agent-hub/agent-hub.db, "
                "or ~/.local/share/agent-hub/agent-hub.db."
            ),
            show_default=False,
        ),
    ] = None,
) -> None:
    """Serve the control plane (API and web app) on 127.0.0.1 until interrupted."""
    try:
        db_path = db or default_database_path(os.environ)
        registry_path = default_registry_path(os.environ)
    except CliError as error:
        fail(f"error: {error}")
    try:
        sock = bind_loopback(port)
    except PortInUseError as error:
        fail(f"error: {error}")
    except OSError as error:
        fail(f"error: cannot listen on {LOOPBACK}:{port}: {error.strerror or error}")
    settings = ApiSettings(
        db_path=db_path,
        registry_path=registry_path,
        port=port,
        running_version=version("agent-hub-cli"),
    )
    app = create_app(settings)
    typer.echo(f"agent-hub at http://{LOOPBACK}:{port}")
    configure_logging()
    serve_on(app, sock)
