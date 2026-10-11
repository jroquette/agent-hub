"""``hub agent``: Claude Code started from the hub with every repo of ``hub.json`` attached.

The hub is ``AGENT_HUB_ROOT`` (the ``./hub`` shim's folder) or the cwd. Each repo folder
``../<dir>`` is attached with ``--add-dir`` (a missing one is named on stderr and skipped); the
repos' ``AGENTS.md`` (``--add-dir`` loads a ``CLAUDE.md`` but not its imports) go to one context
file, ``brain/auto/agent-context.md``, written through a temporary file and replaced on each
launch; Claude Code's auto memory stays in the hub's brain. Then the process becomes ``claude``
(``os.execvp``), so the terminal, signals and exit code are Claude Code's. Every argument after
``agent``, ``--help`` and ``--`` included, goes to ``claude`` as it is. Without ``claude`` on
``PATH`` nothing is written and the exit is 1 (``./hub`` keeps 127 for a missing uv).
"""

import os
import shutil
from pathlib import Path
from typing import Final

import typer
import typer.core
from typer._click.core import Context

from agent_hub.cli.claude_launch import claude_missing_line, launch_claude
from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.errors import LaunchError
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_path
from agent_hub.core.workspace.agent_launch import CLAUDE, missing_repo_warning

COMMAND: Final = "agent"
CONTEXT_FILE: Final = "brain/auto/agent-context.md"
CLAUDE_MISSING: Final = claude_missing_line(COMMAND)


class PassThroughCommand(typer.core.TyperCommand):
    """A command that parses nothing: every argument, options and ``--`` included, is kept."""

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        ctx.args = list(args)
        return []


def agent(context: typer.Context) -> None:
    """Start Claude Code with every repo in hub.json attached; every argument goes to claude."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    config = load_effective_config_or_exit(root).config
    if shutil.which(CLAUDE) is None:
        fail(CLAUDE_MISSING)
    folders: list[tuple[str, Path]] = []
    for repo in config.repos:
        folder = root.parent / repo.dir
        if not folder.is_dir():
            typer.echo(missing_repo_warning(shown_path(str(folder))), err=True)
            continue
        folders.append((repo.dir, folder))
    try:
        launch_claude(
            hub=root, folders=folders, context_file=root / CONTEXT_FILE, extra=context.args
        )
    except LaunchError as error:
        fail(f"hub {COMMAND}: {error}")
