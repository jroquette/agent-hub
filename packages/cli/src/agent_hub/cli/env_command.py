"""``hub env``: list, show and change the declared environments and services, without a prompt.

The hub is ``AGENT_HUB_ROOT`` or the cwd; ``hub.local.json`` is read from the identity home
(``local_home``). ``list`` and ``show`` print the effective view of both files, or one JSON
object with ``--json`` (names and references only: the files hold no credential value). Exit 0
on success, 1 on an invalid file or a refused change, 2 on a usage error
(docs/design/environments.md § ``hub env``).
"""

import os
import re
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.hub_config.environments import MAX_NAME_CHARS
from agent_hub.core.hub_config.text_shapes import SAFE_SEGMENT
from agent_hub.core.json_form import dump_json
from agent_hub.core.secret_shapes import secret_kind
from agent_hub.core.workspace.environment_lines import (
    environment_json,
    environments_json,
    list_lines,
    show_lines,
)

COMMAND: Final = "env"
# A name the command echoes: a safe segment without a secret's shape, else this placeholder.
HIDDEN_NAME: Final = "<name>"
_NAME = re.compile(rf"{SAFE_SEGMENT}")

env_app = typer.Typer(
    name=COMMAND,
    no_args_is_help=True,
    help="List, show and change the declared environments and services.",
)

AsJson = Annotated[bool, typer.Option("--json", help="Print one JSON object instead of lines.")]
Name = Annotated[str, typer.Argument(metavar="NAME", help="The environment's name.")]


def shown_name(name: str) -> str:
    """``name`` as given when it is a valid name with no secret's shape, else ``<name>``."""
    if len(name) <= MAX_NAME_CHARS and _NAME.fullmatch(name) and secret_kind(name) is None:
        return name
    return HIDDEN_NAME


@env_app.command("list")
def list_command(*, as_json: AsJson = False) -> None:
    """List the environments of hub.json and hub.local.json, the services and blocked entries."""
    view = _view()
    if as_json:
        typer.echo(dump_json(environments_json(view)).decode(), nl=False)
        return
    for line in list_lines(view):
        typer.echo(line)


@env_app.command("show")
def show_command(name: Name, *, as_json: AsJson = False) -> None:
    """Show one environment: its access, source, credential names and endpoints."""
    view = _view()
    lines = show_lines(view, name)
    if lines is None:
        fail(f"hub env show: no environment {shown_name(name)} in hub.json or hub.local.json")
    if as_json:
        typer.echo(dump_json(environment_json(view, name)).decode(), nl=False)
        return
    for line in lines:
        typer.echo(line)


def _view() -> EffectiveEnvironments:
    root = hub_root_or_exit(os.environ, command=COMMAND)
    effective = load_effective_config_or_exit(root)
    return effective_environments(effective.config, effective.local)
