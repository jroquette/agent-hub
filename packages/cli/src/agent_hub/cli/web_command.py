"""``hub web``: serve the control plane's API and web app on 127.0.0.1 (D2).

The only cli module that imports ``agent_hub.api`` (import contract, erratum E1). ``--host`` may
name another loopback address; any other address is refused unless ``AGENT_HUB_IN_CONTAINER``
is ``1``, which only the agent-hub image sets (ADR 0022). The Host and Origin checks stay
loopback-only, plus the exact names of ``AGENT_HUB_ALLOWED_HOSTS``.
"""

import ipaddress
import os
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from agent_hub.api.composition import build_app
from agent_hub.api.json_logging import configure_logging
from agent_hub.api.local_security import ALLOWED_HOSTS_VARIABLE, parse_allowed_hosts
from agent_hub.api.server import LOOPBACK, PortInUseError, bind_address, serve_on
from agent_hub.api.settings import DEFAULT_PORT, ApiSettings
from agent_hub.cli.command_exits import fail
from agent_hub.cli.database_path import account_home_directory, default_database_path
from agent_hub.cli.effective_config import git_identity_reader
from agent_hub.cli.errors import CliError, HomeDirectoryNotFoundError, ProjectsRootError
from agent_hub.core.hub_config.effective_identity import GitReader
from agent_hub.storage.errors import DatabaseAccessError

REGISTRY_DIR = "agent-hub"
REGISTRY_FILE = "hubs.json"
PROJECTS_VARIABLE = "AGENT_HUB_CLAUDE_PROJECTS"
CONTAINER_VARIABLE = "AGENT_HUB_IN_CONTAINER"
LOCALHOST = "localhost"
IPV6_LOOPBACK = "::1"
OUTSIDE_LOOPBACK = f"error: binding outside loopback needs {CONTAINER_VARIABLE}=1"
NOT_AN_ADDRESS = "error: --host must be an IP address or localhost"
USAGE = 2


def _home(environ: Mapping[str, str]) -> Path:
    """``HOME`` when absolute, else the account's home, as for the event database."""
    for home in (environ.get("HOME", ""), account_home_directory() or ""):
        if home and Path(home).is_absolute():
            return Path(home)
    raise HomeDirectoryNotFoundError


def default_registry_path(environ: Mapping[str, str]) -> Path:
    """``$XDG_CONFIG_HOME/agent-hub/hubs.json``, else ``~/.config/agent-hub/hubs.json`` (D18).

    ``XDG_CONFIG_HOME`` counts only when absolute; the home directory is found as for the
    event database (``HOME`` when absolute, else the account's home).
    """
    config_home = environ.get("XDG_CONFIG_HOME", "")
    if config_home and Path(config_home).is_absolute():
        return Path(config_home) / REGISTRY_DIR / REGISTRY_FILE
    return _home(environ) / ".config" / REGISTRY_DIR / REGISTRY_FILE


def claude_projects_root(environ: Mapping[str, str]) -> Path:
    """The only folder the live transcript tail reads (D9): ``AGENT_HUB_CLAUDE_PROJECTS`` when
    set (absolute only), else ``~/.claude/projects``."""
    configured = environ.get(PROJECTS_VARIABLE, "")
    if configured:
        if not Path(configured).is_absolute():
            raise ProjectsRootError
        return Path(configured)
    return _home(environ) / ".claude" / "projects"


def _usage_error(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(USAGE)


def bind_host(host: str, environ: Mapping[str, str]) -> str:
    """The address to bind for ``--host``: ``localhost`` is 127.0.0.1, a loopback address is
    itself, and any other address only when ``AGENT_HUB_IN_CONTAINER`` is ``1``; else exit 2."""
    if host == LOCALHOST:
        return LOOPBACK
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        _usage_error(NOT_AN_ADDRESS)
    if not address.is_loopback and environ.get(CONTAINER_VARIABLE) != "1":
        _usage_error(OUTSIDE_LOOPBACK)
    return str(address)


def _allowed_hosts_or_exit(environ: Mapping[str, str], port: int) -> frozenset[str]:
    try:
        return parse_allowed_hosts(environ.get(ALLOWED_HOSTS_VARIABLE, ""), port=port)
    except ValueError as error:
        _usage_error(f"error: {error}")


def _startup_lines(bound: str, port: int) -> list[str]:
    """The URL line, then the bound address when it is not 127.0.0.1."""
    if bound == LOOPBACK:
        return [f"agent-hub at http://{LOOPBACK}:{port}"]
    shown = f"[{bound}]" if ":" in bound else bound
    # Only the IPv6 loopback is not reachable at 127.0.0.1.
    url_host = shown if bound == IPV6_LOOPBACK else LOOPBACK
    return [f"agent-hub at http://{url_host}:{port}", f"listening on {shown}:{port}"]


def _git_reader(hub_path: str) -> GitReader:
    """Git config read in the hub's folder, as ``hub doctor`` reads it for the branch prefix."""
    read_git, _ = git_identity_reader(Path(hub_path))
    return read_git


def web(
    *,
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help=(
                "Address to listen on: 127.0.0.1, another loopback address or localhost. Any "
                "other address only inside the agent-hub container (AGENT_HUB_IN_CONTAINER=1)."
            ),
        ),
    ] = LOOPBACK,
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
    bound = bind_host(host, os.environ)
    extra_hosts = _allowed_hosts_or_exit(os.environ, port)
    try:
        db_path = db or default_database_path(os.environ)
        registry_path = default_registry_path(os.environ)
        projects_root = claude_projects_root(os.environ)
    except CliError as error:
        fail(f"error: {error}")
    try:
        sock = bind_address(bound, port)
    except PortInUseError as error:
        fail(f"error: {error}")
    except OSError as error:
        fail(f"error: cannot listen on {bound}:{port}: {error.strerror or error}")
    settings = ApiSettings(
        db_path=db_path,
        registry_path=registry_path,
        port=port,
        running_version=version("agent-hub-cli"),
        allowed_hosts=extra_hosts,
    )
    try:
        app = build_app(settings, projects_root=projects_root, read_git=_git_reader)
    except DatabaseAccessError as error:
        sock.close()
        fail(f"error: {error}")
    for line in _startup_lines(bound, port):
        typer.echo(line)
    configure_logging()
    serve_on(app, sock)
