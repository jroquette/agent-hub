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

import contextlib
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Final

import typer
import typer.core
from typer._click.core import Context

from agent_hub.cli.command_exits import fail
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_path
from agent_hub.core.workspace.agent_launch import (
    CLAUDE,
    context_text,
    launch_argv,
    missing_repo_warning,
    settings_json,
)

COMMAND: Final = "agent"
CONTEXT_FILE: Final = "brain/auto/agent-context.md"
# Claude Code loads the CLAUDE.md of each --add-dir folder only with this set.
ADDITIONAL_DIRECTORIES_VARIABLE: Final = "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD"
CLAUDE_MISSING: Final = (
    "hub agent: Claude Code (claude) is not on PATH;"
    " install it: https://docs.claude.com/en/docs/claude-code/setup"
)
_AGENTS_FILE: Final = "AGENTS.md"


class PassThroughCommand(typer.core.TyperCommand):
    """A command that parses nothing: every argument, options and ``--`` included, is kept."""

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        ctx.args = list(args)
        return []


def agent(context: typer.Context) -> None:
    """Start Claude Code with every repo in hub.json attached; every argument goes to claude."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    config = load_hub_config_or_exit(root / FILE_LABEL)
    if shutil.which(CLAUDE) is None:
        fail(CLAUDE_MISSING)
    attached: list[str] = []
    sections: list[tuple[str, bytes]] = []
    for repo in config.repos:
        folder = root.parent / repo.dir
        if not folder.is_dir():
            typer.echo(missing_repo_warning(shown_path(str(folder))), err=True)
            continue
        attached.append(str(folder))
        agents = _regular_file_bytes(folder / _AGENTS_FILE)
        if agents is not None:
            sections.append((repo.dir, agents))
    context_file = root / CONTEXT_FILE
    _write_replacing(context_file, context_text(sections))
    argv = launch_argv(
        attached=attached,
        context_file=str(context_file),
        settings=settings_json(str(root)),
        extra=context.args,
    )
    os.environ[ADDITIONAL_DIRECTORIES_VARIABLE] = "1"
    os.execvp(CLAUDE, argv)  # noqa: S606 - an argv list, no shell: claude replaces this process


def _regular_file_bytes(path: Path) -> bytes | None:
    # As the old launcher's [ -f ]: a link is followed; a FIFO or a folder is never opened.
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return None
        return path.read_bytes()
    except OSError:
        return None


def _write_replacing(path: Path, content: bytes) -> None:
    """Write ``content`` to a temporary file beside ``path``, then put it in place at once."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
    except OSError as error:
        fail(f"hub agent: cannot write {shown_path(str(path))}: {error.strerror or error}")
