"""Entry point of the hub command."""

from importlib.metadata import version
from typing import Annotated

import typer

from agent_hub.cli.command_table import HubGroup

# Each subcommand is imported when it runs: its name and help are in command_table.
app = typer.Typer(name="hub", cls=HubGroup, no_args_is_help=True)


def _print_version(*, requested: bool) -> None:
    if requested:
        typer.echo(version("agent-hub-cli"))
        raise typer.Exit


@app.callback()
def main(
    *,
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Print the version and exit.",
        ),
    ] = False,
) -> None:
    """Create, operate and observe agent hubs."""
