"""The hub generator commands (SPEC layer 1): public surface now, behavior in Phase 1."""

from typing import Annotated, NoReturn

import typer

NOT_IMPLEMENTED = "not implemented yet (Phase 1)"
# A usage-level failure, so a script that calls a stub by accident stops (D7).
NOT_IMPLEMENTED_EXIT_CODE = 2


def init(
    project: Annotated[
        str, typer.Argument(metavar="PROJECT", help="Name of the project the hub is for.")
    ],
    *,
    repos: Annotated[
        str,
        typer.Option(
            "--repos", help="Comma-separated repos of the project, e.g. org/backend,org/frontend."
        ),
    ],
    tracker: Annotated[
        str, typer.Option("--tracker", help="Task tracker and team key, e.g. linear:LOK.")
    ],
) -> None:
    """Create a hub for a project with its repos and task tracker."""
    _not_implemented()


def sync() -> None:
    """Reapply the hub templates without overwriting what the project customized."""
    _not_implemented()


def doctor() -> None:
    """Check the hub's rules, links, dead references and instruction size."""
    _not_implemented()


def _not_implemented() -> NoReturn:
    typer.echo(NOT_IMPLEMENTED, err=True)
    raise typer.Exit(NOT_IMPLEMENTED_EXIT_CODE)
