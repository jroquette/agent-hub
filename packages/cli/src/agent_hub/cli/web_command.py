"""``hub web``: serve the control plane's API and web app on 127.0.0.1 (D2).

The only cli module that imports ``agent_hub.api`` (import contract, erratum E1). ``--host`` may
name another loopback address; any other address is refused unless ``AGENT_HUB_IN_CONTAINER``
is ``1``, which only the agent-hub image sets (ADR 0022). The Host and Origin checks stay
loopback-only, plus the exact names of ``AGENT_HUB_ALLOWED_HOSTS``.

Each start mints a fresh token for the agent-session routes and prints it once in the URL
(``?token=``); the browser trades it for a cookie (P6, ADR 0031). The token is held in memory
only: no file, no log line. In the container no token is minted and session control is off
(L2). The session bounds are options with ``AGENT_HUB_*`` variables (P14); ``--open`` opens
the URL in the default browser through a private file, as Jupyter does: the browser is given a
``file://`` page only this user can read (mode 0600) that redirects to the token URL, so the
token never reaches a command line another local user can read; the file is removed when the
server stops.
"""

import contextlib
import html
import ipaddress
import os
import tempfile
import webbrowser
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from agent_hub.api.composition import build_app
from agent_hub.api.json_logging import configure_logging
from agent_hub.api.local_security import ALLOWED_HOSTS_VARIABLE, parse_allowed_hosts
from agent_hub.api.server import LOOPBACK, PortInUseError, bind_address, serve_on
from agent_hub.api.session_token import mint_token
from agent_hub.api.settings import DEFAULT_PORT, ApiSettings
from agent_hub.cli.command_exits import fail
from agent_hub.cli.database_path import account_home_directory, default_database_path
from agent_hub.cli.effective_config import git_identity_reader
from agent_hub.cli.errors import CliError, HomeDirectoryNotFoundError, ProjectsRootError
from agent_hub.core.agent_sessions.limits import SessionLimits
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


def startup_url(bound: str, port: int, token: str | None) -> str:
    """The address to open: the loopback at ``port`` (the IPv6 one when bound there), with
    ``/?token=`` when a token was minted."""
    # Only the IPv6 loopback is not reachable at 127.0.0.1.
    url_host = f"[{bound}]" if bound == IPV6_LOOPBACK else LOOPBACK
    url = f"http://{url_host}:{port}"
    return url if token is None else f"{url}/?token={token}"


def redirect_page(url: str) -> str:
    """The page ``--open`` hands the browser: an immediate redirect to ``url``."""
    target = html.escape(url, quote=True)
    return (
        '<!doctype html>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="refresh" content="0;url={target}">\n'
        f'<title>agent-hub</title>\n<p><a href="{target}">Open agent-hub</a></p>\n'
    )


def write_redirect_file(url: str) -> Path:
    """A new ``redirect_page(url)`` file only this user can read or write (mode 0600)."""
    descriptor, name = tempfile.mkstemp(prefix="agent-hub-open-", suffix=".html")
    with os.fdopen(descriptor, "w", encoding="utf-8") as page:
        page.write(redirect_page(url))
    os.chmod(name, 0o600)
    return Path(name)


def _startup_lines(bound: str, url: str, port: int) -> list[str]:
    """The URL line, then the bound address when it is not 127.0.0.1."""
    if bound == LOOPBACK:
        return [f"agent-hub at {url}"]
    shown = f"[{bound}]" if ":" in bound else bound
    return [f"agent-hub at {url}", f"listening on {shown}:{port}"]


def _limit_bound(name: str, attribute: str) -> int:
    """A ``SessionLimits`` field's ``ge`` or ``le`` bound, so each option's range is the model's."""
    for constraint in SessionLimits.model_fields[name].metadata:
        value = getattr(constraint, attribute, None)
        if isinstance(value, int):
            return value
    raise LookupError(f"SessionLimits.{name} has no {attribute} bound")


def _limit_option(name: str, *, flag: str, variable: str, help_text: str) -> Any:  # noqa: ANN401 -- typer.Option is Any
    """The option of one ``SessionLimits`` field, its variable and the model's range."""
    low, high = _limit_bound(name, "ge"), _limit_bound(name, "le")
    return typer.Option(flag, envvar=variable, help=help_text, min=low, max=high)


_DEFAULTS = SessionLimits()


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
    sessions_max: Annotated[
        int,
        _limit_option(
            "sessions_max",
            flag="--sessions-max",
            variable="AGENT_HUB_SESSIONS_MAX",
            help_text="Live agent sessions.",
        ),
    ] = _DEFAULTS.sessions_max,
    session_idle_seconds: Annotated[
        int,
        _limit_option(
            "idle_seconds",
            flag="--session-idle-seconds",
            variable="AGENT_HUB_SESSION_IDLE_SECONDS",
            help_text="Seconds an idle session lives.",
        ),
    ] = _DEFAULTS.idle_seconds,
    permission_timeout_seconds: Annotated[
        int,
        _limit_option(
            "permission_timeout_seconds",
            flag="--permission-timeout-seconds",
            variable="AGENT_HUB_PERMISSION_TIMEOUT_SECONDS",
            help_text="Seconds a permission request waits before it is denied.",
        ),
    ] = _DEFAULTS.permission_timeout_seconds,
    session_log_records: Annotated[
        int,
        _limit_option(
            "log_records",
            flag="--session-log-records",
            variable="AGENT_HUB_SESSION_LOG_RECORDS",
            help_text="Records one session's log holds.",
        ),
    ] = _DEFAULTS.log_records,
    session_log_bytes: Annotated[
        int,
        _limit_option(
            "log_bytes",
            flag="--session-log-bytes",
            variable="AGENT_HUB_SESSION_LOG_BYTES",
            help_text="Bytes of text one session's log holds.",
        ),
    ] = _DEFAULTS.log_bytes,
    message_max_bytes: Annotated[
        int,
        _limit_option(
            "message_max_bytes",
            flag="--message-max-bytes",
            variable="AGENT_HUB_MESSAGE_MAX_BYTES",
            help_text="Bytes of one message to a session.",
        ),
    ] = _DEFAULTS.message_max_bytes,
    cloud_timeout_seconds: Annotated[
        int,
        _limit_option(
            "cloud_timeout_seconds",
            flag="--cloud-timeout-seconds",
            variable="AGENT_HUB_CLOUD_TIMEOUT_SECONDS",
            help_text="Seconds a claude --cloud call may take.",
        ),
    ] = _DEFAULTS.cloud_timeout_seconds,
    session_retention_days: Annotated[
        int,
        _limit_option(
            "retention_days",
            flag="--session-retention-days",
            variable="AGENT_HUB_SESSION_RETENTION_DAYS",
            help_text="Days an ended session's log is kept.",
        ),
    ] = _DEFAULTS.retention_days,
    open_browser: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open the printed address in the default browser."),
    ] = False,
) -> None:
    """Serve the control plane (API and web app) on 127.0.0.1 until interrupted."""
    limits = SessionLimits(
        sessions_max=sessions_max,
        idle_seconds=session_idle_seconds,
        permission_timeout_seconds=permission_timeout_seconds,
        log_records=session_log_records,
        log_bytes=session_log_bytes,
        message_max_bytes=message_max_bytes,
        cloud_timeout_seconds=cloud_timeout_seconds,
        retention_days=session_retention_days,
    )
    in_container = os.environ.get(CONTAINER_VARIABLE) == "1"
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
        session_token=None if in_container else mint_token(),
        sessions_off=in_container,
        limits=limits,
        bound_host=bound,
    )
    try:
        app = build_app(settings, projects_root=projects_root, read_git=_git_reader)
    except DatabaseAccessError as error:
        sock.close()
        fail(f"error: {error}")
    url = startup_url(bound, port, settings.session_token)
    for line in _startup_lines(bound, url, port):
        typer.echo(line)
    configure_logging()
    redirect = write_redirect_file(url) if open_browser else None
    try:
        if redirect is not None:
            webbrowser.open(redirect.as_uri())
        serve_on(app, sock)
    finally:
        if redirect is not None:
            with contextlib.suppress(OSError):
                redirect.unlink()
