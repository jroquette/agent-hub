"""Where the hook sensor's spool and Claude Code's transcripts are, for ``hub web`` and ``collect``.

Kept out of ``web_command``, which imports the API server: ``collect`` reads both too, and a cli
module that imported them from there would reach ``agent_hub.api`` (the ``cli-api-web-command``
import contract).
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from agent_hub.cli.database_path import account_home_directory
from agent_hub.cli.errors import ProjectsRootError
from agent_hub.cli.registry_path import home_directory

PROJECTS_VARIABLE: Final = "AGENT_HUB_CLAUDE_PROJECTS"
SPOOL_DIR: Final = "agent-hub"


def default_spool_folder(
    environ: Mapping[str, str], *, account_home: Callable[[], str | None] | None = None
) -> Path:
    """``$XDG_STATE_HOME/agent-hub``, else ``~/.local/state/agent-hub``: where the sensor spools.

    ``XDG_STATE_HOME`` counts only when absolute, as the sensor reads it; the home directory is
    found as for the event database (``home_directory``).
    """
    state_home = environ.get("XDG_STATE_HOME", "")
    if state_home and Path(state_home).is_absolute():
        return Path(state_home) / SPOOL_DIR
    home = home_directory(environ, account_home=account_home or account_home_directory)
    return home / ".local" / "state" / SPOOL_DIR


def claude_projects_root(environ: Mapping[str, str]) -> Path:
    """The only folder the transcript tail reads (D9): ``AGENT_HUB_CLAUDE_PROJECTS`` when set
    (absolute only), else ``~/.claude/projects``."""
    configured = environ.get(PROJECTS_VARIABLE, "")
    if configured:
        if not Path(configured).is_absolute():
            raise ProjectsRootError
        return Path(configured)
    return home_directory(environ, account_home=account_home_directory) / ".claude" / "projects"
