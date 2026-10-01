"""Entry point of the hub command."""

from importlib.metadata import version
from typing import Annotated

import typer

from agent_hub.cli.brief_command import brief
from agent_hub.cli.collect import collect
from agent_hub.cli.doctor_command import doctor
from agent_hub.cli.generator import init
from agent_hub.cli.sync_command import sync
from agent_hub.cli.worktree_command import worktree

app = typer.Typer(name="hub", no_args_is_help=True)


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


app.command("collect")(collect)
app.command("init")(init)
app.command("sync")(sync)
app.command("doctor")(doctor)
app.command("worktree")(worktree)
app.command("brief")(brief)
