"""Entry point of the hub command."""

from importlib.metadata import version
from typing import Annotated

import typer

from agent_hub.cli.agent_command import PassThroughCommand, agent
from agent_hub.cli.bench_command import bench
from agent_hub.cli.brief_command import brief
from agent_hub.cli.collect import collect
from agent_hub.cli.doctor_command import doctor
from agent_hub.cli.generator import init
from agent_hub.cli.next_command import next_command
from agent_hub.cli.run_engine import run
from agent_hub.cli.setup_command import setup
from agent_hub.cli.ship_command import ship
from agent_hub.cli.start_command import start
from agent_hub.cli.step_command import step_app
from agent_hub.cli.sync_command import sync
from agent_hub.cli.validate_output_command import validate_output
from agent_hub.cli.web_command import web
from agent_hub.cli.workflow_command import workflow_app
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
app.command("setup")(setup)
app.command("worktree")(worktree)
app.command("brief")(brief)
app.command("agent", cls=PassThroughCommand, add_help_option=False)(agent)
app.command("next")(next_command)
app.command("run")(run)
app.command("ship")(ship)
app.command("bench")(bench)
app.command("start")(start)
app.command("web")(web)
app.command("validate-output")(validate_output)
app.add_typer(workflow_app, name="workflow")
app.add_typer(step_app, name="step")
