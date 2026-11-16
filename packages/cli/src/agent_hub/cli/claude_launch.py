"""The Claude Code launch ``hub agent`` and ``hub start`` share: context file, argv, exec.

Each attached folder's ``AGENTS.md`` (``--add-dir`` loads a ``CLAUDE.md`` but not its imports)
goes under a header naming the folder to one context file, written through a temporary file
and replaced at once; Claude Code's auto memory stays in the hub's brain (``settings_json``).
Then the process becomes ``claude`` (``os.execvp``), so the terminal, signals and exit code are
Claude Code's. A failure raises ``LaunchError``; each command prints it after its own prefix.
"""

import contextlib
import os
import stat
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Final, NoReturn

from agent_hub.cli.errors import LaunchError
from agent_hub.cli.init_report import shown_path
from agent_hub.core.workspace.agent_launch import CLAUDE, context_text, launch_argv, settings_json

# Claude Code loads the CLAUDE.md of each --add-dir folder only with this set.
ADDITIONAL_DIRECTORIES_VARIABLE: Final = "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD"
_AGENTS_FILE: Final = "AGENTS.md"
_SETUP_URL: Final = "https://docs.claude.com/en/docs/claude-code/setup"


def claude_missing_line(command: str) -> str:
    """The line ``hub <command>`` stops on when ``claude`` is not on ``PATH``."""
    return f"hub {command}: Claude Code (claude) is not on PATH; install it: {_SETUP_URL}"


def launch_claude(
    *,
    hub: Path,
    folders: Sequence[tuple[str, Path]],
    context_file: Path,
    extra: Sequence[str],
) -> NoReturn:
    """Exec ``claude`` from the cwd with ``folders`` attached and ``extra`` as the last arguments.

    ``folders`` are ``(label, path)`` pairs, attached in order; the label names the folder in
    the context file's header (``../<label>``). Raises ``LaunchError`` when the context file
    cannot be written or ``claude`` cannot start.
    """
    sections: list[tuple[str, bytes]] = []
    for label, folder in folders:
        agents = _regular_file_bytes(folder / _AGENTS_FILE)
        if agents is not None:
            sections.append((label, agents))
    _write_replacing(context_file, context_text(sections))
    argv = launch_argv(
        attached=[str(folder) for _, folder in folders],
        context_file=str(context_file),
        settings=settings_json(str(hub)),
        extra=extra,
    )
    os.environ[ADDITIONAL_DIRECTORIES_VARIABLE] = "1"
    try:
        os.execvp(CLAUDE, argv)  # noqa: S606 - an argv list, no shell: claude replaces this process
    except OSError as error:
        msg = f"cannot start claude: {error.strerror or error}"
        raise LaunchError(msg) from None


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
        msg = f"cannot write {shown_path(str(path))}: {error.strerror or error}"
        raise LaunchError(msg) from None
