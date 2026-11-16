"""Where ``hub`` keeps its event database when neither ``--db`` nor ``AGENT_HUB_DB`` is given."""

import os
import pwd
from collections.abc import Callable, Mapping
from pathlib import Path

from agent_hub.cli.errors import HomeDirectoryNotFoundError

DATABASE_DIR = "agent-hub"
DATABASE_FILE = "agent-hub.db"


def default_database_path(
    environ: Mapping[str, str], *, account_home: Callable[[], str | None] | None = None
) -> Path:
    """``$XDG_DATA_HOME/agent-hub/agent-hub.db``, else ``~/.local/share/agent-hub/agent-hub.db``.

    ``XDG_DATA_HOME`` counts only when set, non-empty and absolute (the XDG Base Directory
    spec ignores a relative one). The home directory is ``HOME`` when non-empty and absolute,
    else the account's home from ``account_home`` (default: the password database) under the
    same rule; with neither, ``HomeDirectoryNotFoundError``. ``Path.home()`` is not used: it
    turns an empty ``HOME`` into ``/`` or the working directory and can raise.
    """
    xdg_data_home = environ.get("XDG_DATA_HOME", "")
    if _is_absolute(xdg_data_home):
        return Path(xdg_data_home) / DATABASE_DIR / DATABASE_FILE
    home = _home_directory(environ, account_home or account_home_directory)
    return home / ".local" / "share" / DATABASE_DIR / DATABASE_FILE


def account_home_directory() -> str | None:
    """The current account's home directory from the password database, if it has an entry."""
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        return None


def _home_directory(environ: Mapping[str, str], account_home: Callable[[], str | None]) -> Path:
    home = environ.get("HOME", "")
    if _is_absolute(home):
        return Path(home)
    home = account_home() or ""
    if _is_absolute(home):
        return Path(home)
    raise HomeDirectoryNotFoundError


def _is_absolute(directory: str) -> bool:
    return bool(directory) and Path(directory).is_absolute()
