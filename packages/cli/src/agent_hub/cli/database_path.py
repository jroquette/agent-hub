"""Where ``hub`` keeps its event database when neither ``--db`` nor ``AGENT_HUB_DB`` is given."""

from collections.abc import Mapping
from pathlib import Path

DATABASE_DIR = "agent-hub"
DATABASE_FILE = "agent-hub.db"


def default_database_path(environ: Mapping[str, str]) -> Path:
    """``$XDG_DATA_HOME/agent-hub/agent-hub.db``, else ``~/.local/share/agent-hub/agent-hub.db``.

    ``XDG_DATA_HOME`` counts only when set, non-empty and absolute (the XDG Base Directory
    spec ignores a relative one). The home directory is ``HOME``, or the user's home from the
    system when ``HOME`` is unset.
    """
    return _data_home(environ) / DATABASE_DIR / DATABASE_FILE


def _data_home(environ: Mapping[str, str]) -> Path:
    xdg_data_home = environ.get("XDG_DATA_HOME", "")
    if xdg_data_home and Path(xdg_data_home).is_absolute():
        return Path(xdg_data_home)
    home = environ.get("HOME")
    return (Path(home) if home else Path.home()) / ".local" / "share"
