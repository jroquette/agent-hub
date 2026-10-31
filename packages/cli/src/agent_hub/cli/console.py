"""The entry point of the installed ``hub`` command.

When the arguments are exactly ``workflow list`` and no shell completion is asked, ``main`` lists
the hub's workflows itself, with the garbage collector off. That path loads none of Typer, the
``HubConfig`` model and the ``hub.json`` reader. It prints only a listing that has no problem, no
escape sequence and no text that stdout cannot encode as it is. In every other case nothing is
printed yet, and the Typer app of ``agent_hub.cli.main`` runs instead, so the output stays the
Typer command's. ``python -m agent_hub.cli`` always runs the Typer app.
"""

import errno
import gc
import os
import sys
from pathlib import Path
from typing import Final

_LIST_ARGS: Final = ("workflow", "list")
# Set when the shell asks the Typer app to complete a command line.
_COMPLETE_VARIABLE: Final = "_HUB_COMPLETE"
# hub_root's names: importing that module would load Typer.
_HUB_ROOT_VARIABLE: Final = "AGENT_HUB_ROOT"
_HUB_JSON: Final = "hub.json"
# The codes Typer exits with on Ctrl-C and on a stdout pipe that its reader closed.
_INTERRUPTED_EXIT: Final = 130
_CLOSED_PIPE_EXIT: Final = 1


def main() -> None:
    """Run ``hub`` with this process's arguments."""
    if tuple(sys.argv[1:]) != _LIST_ARGS or _COMPLETE_VARIABLE in os.environ:
        _run_typer_app()
        return
    gc.disable()
    try:
        text = _listing_text()
    except KeyboardInterrupt:
        raise SystemExit(_INTERRUPTED_EXIT) from None
    except Exception:  # noqa: BLE001 - the Typer app meets it again and reports it as it would
        text = None
    if text is None:
        gc.enable()
        _run_typer_app()
        return
    _print_at_once(text)


def _listing_text() -> str | None:
    """What ``hub workflow list`` prints, or ``None`` when the Typer app must run: not a hub, a
    problem, an escape sequence, or text that stdout cannot encode as it is."""
    root = os.path.realpath(os.environ.get(_HUB_ROOT_VARIABLE) or os.curdir)
    if not os.path.lexists(os.path.join(root, _HUB_JSON)):
        return None
    from agent_hub.core.workflows.catalog import (  # noqa: PLC0415 - only this listing loads workflows
        check_workflows,
    )
    from agent_hub.generator.workflow_source import (  # noqa: PLC0415 - only this listing loads workflows
        DiscoveredWorkflowSource,
    )

    catalog = check_workflows(DiscoveredWorkflowSource(Path(root)))
    if catalog.problems:
        return None
    lines: list[str] = []
    for plan in catalog.plans:
        document = plan.document
        line = f"{document.name}  {len(document.nodes)} nodes  {document.description or ''}"
        lines.append(f"{line.rstrip()}\n")
    text = "".join(lines)
    # Click drops escape sequences when stdout is not a terminal.
    if "\x1b" in text or not _stdout_takes(text):
        return None
    return text


def _stdout_takes(text: str) -> bool:
    """Whether stdout's encoding takes ``text`` strictly. Then the bytes are the ones Click prints:
    Click writes UTF-8 to a stdout set to ASCII, whatever that stdout's error handler is."""
    try:
        text.encode(sys.stdout.encoding)
    except UnicodeEncodeError:
        return False
    return True


def _print_at_once(text: str) -> None:
    """Write ``text`` in one write: Ctrl-C exits 130 and a closed pipe exits 1, as under Typer."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except KeyboardInterrupt:
        raise SystemExit(_INTERRUPTED_EXIT) from None
    except OSError as error:
        if error.errno != errno.EPIPE:
            raise
        # Stdout now goes nowhere, so the interpreter's last flush cannot fail at exit.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
        raise SystemExit(_CLOSED_PIPE_EXIT) from None


def _run_typer_app() -> None:
    from agent_hub.cli.main import app  # noqa: PLC0415 - the listing path never loads Typer

    app()
