"""Where the hub registry ``hubs.json`` lives (D18), for ``hub web`` and ``--hub NAME``.

Kept out of ``web_command``, which imports the API server: any other cli module that imported
it from there would reach ``agent_hub.api`` (the ``cli-api-web-command`` import contract).
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from agent_hub.cli.database_path import account_home_directory
from agent_hub.cli.errors import HomeDirectoryNotFoundError

REGISTRY_DIR = "agent-hub"
REGISTRY_FILE = "hubs.json"


def default_registry_path(
    environ: Mapping[str, str], *, account_home: Callable[[], str | None] | None = None
) -> Path:
    """``$XDG_CONFIG_HOME/agent-hub/hubs.json``, else ``~/.config/agent-hub/hubs.json`` (D18).

    ``XDG_CONFIG_HOME`` counts only when absolute; the home directory is found as for the
    event database (``home_directory``).
    """
    config_home = environ.get("XDG_CONFIG_HOME", "")
    if config_home and Path(config_home).is_absolute():
        return Path(config_home) / REGISTRY_DIR / REGISTRY_FILE
    return (
        home_directory(environ, account_home=account_home)
        / ".config"
        / REGISTRY_DIR
        / REGISTRY_FILE
    )


def home_directory(
    environ: Mapping[str, str], *, account_home: Callable[[], str | None] | None = None
) -> Path:
    """``HOME`` when absolute, else the account's home from ``account_home`` (default: the
    password database), as for the event database; with neither, ``HomeDirectoryNotFoundError``."""
    home = environ.get("HOME", "")
    if home and Path(home).is_absolute():
        return Path(home)
    home = (account_home or account_home_directory)() or ""
    if home and Path(home).is_absolute():
        return Path(home)
    raise HomeDirectoryNotFoundError
