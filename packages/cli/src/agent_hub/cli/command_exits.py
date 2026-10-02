"""The exit helpers shared by the hub commands: each failure prints to stderr and exits 1.

A stub command or option prints the stub text instead and exits 2.

Every error goes to stderr on its own line, escaped so that it cannot fake a second line.
"""

import os
from collections.abc import Collection
from pathlib import Path
from typing import Final, NoReturn

import typer

from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.core.hub_files.extension_inputs import ExtensionInputs, extension_inputs_from
from agent_hub.core.hub_files.tree_snapshot import TreeSnapshot
from agent_hub.generator.errors import GeneratorError

# Any failure after the usage check: config, modules, target, tree or write.
FAILURE: Final = 1
NOT_IMPLEMENTED: Final = "not implemented yet (Phase 1)"
# A usage-level failure, so a script that calls a stub by accident stops (D7).
NOT_IMPLEMENTED_EXIT_CODE: Final = 2


def not_implemented() -> NoReturn:
    """Stop a stub command (or option): the stub text on stderr, exit 2."""
    typer.echo(NOT_IMPLEMENTED, err=True)
    raise typer.Exit(NOT_IMPLEMENTED_EXIT_CODE)


def root_or_exit(directory: Path | None) -> str:
    """The hub root, taken once: every later step uses this real path (spec Q-9)."""
    given = os.fspath(directory) if directory is not None else os.curdir
    try:
        return os.path.realpath(given)
    except OSError as error:
        # A relative path needs the cwd, which may have been deleted.
        fail(f"{shown_path(given)}: {error.strerror or error}")


def extension_inputs_or_exit(
    tree: TreeSnapshot, *, project: str, siblings: Collection[str]
) -> ExtensionInputs:
    """The project's extension inputs in ``tree``; each problem is one line, then exit 1.

    A sibling that is not a regular file, or an agent or skill name ``hub.lock`` cannot record
    (plan E9), is an input error: nothing is written.
    """
    found = extension_inputs_from(tree, project=project, siblings=siblings)
    if not isinstance(found, ExtensionInputs):
        fail(*(f"{shown_path(path)}: {message}" for path, message in found))
    return found


def fail_generator(error: GeneratorError) -> NoReturn:
    # The error reads "<path>: <cause>"; a note (a temp entry left behind) is one more line.
    notes: list[str] = getattr(error, "__notes__", [])
    fail(str(error), *notes)


def fail(*lines: str) -> NoReturn:
    # One line per problem: text with a line break is shown escaped, so it cannot fake a line.
    for line in lines:
        typer.echo(shown_text(line), err=True)
    raise typer.Exit(FAILURE)
