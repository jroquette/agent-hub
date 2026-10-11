"""``hub setup``: onboard this machine for the hub, then list what is still missing.

The hub is ``AGENT_HUB_ROOT`` when ``./hub`` exports it, else the current folder; without a
``hub.json`` entry there the exit is 2. ``hub.json`` is read once: any problem with it, a pin
other than this release included (plan E1), prints the reader's lines and exits 1 before any
git call. Then the checklist, each item's lines printed as soon as it is decided (so far the
tools and the tracker credential, ``setup_tools``, then the developer's identity,
``setup_identity``, whose proposal and prompt alone go to stderr, and whether git ignores
``hub.local.json`` when it exists), and the totals line ``setup: ...``; the exit is 0 when
every item is ``ok``, else 1.
"""

import os
from typing import Annotated, Final

import typer

from agent_hub.cli import setup_identity, setup_tools
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit, local_home
from agent_hub.cli.run_children import SESSION_HIDDEN, without
from agent_hub.cli.setup_repos import setup_git_env
from agent_hub.core.workspace.setup_checklist import (
    ChecklistItem,
    item_lines,
    setup_exit,
    summary_line,
)

COMMAND: Final = "setup"


class Checklist:
    """The items decided so far, in order; each one's lines go to stdout when it is added."""

    def __init__(self) -> None:
        self._items: list[ChecklistItem] = []

    @property
    def items(self) -> tuple[ChecklistItem, ...]:
        return tuple(self._items)

    def add(self, item: ChecklistItem) -> None:
        self._items.append(item)
        for line in item_lines(item):
            typer.echo(line)


def setup(
    *,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Write a new hub.local.json without asking."),
    ] = False,
) -> None:
    """Set up this machine for the hub: tools, identity, repos, then hub doctor."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    config = load_hub_config_or_exit(root / FILE_LABEL)
    # No token reaches git, which only looks for the main checkout.
    home = local_home(root, environ=without(os.environ, SESSION_HIDDEN))
    checklist = Checklist()
    probe = setup_tools.tool_probe(os.environ, cwd=root)
    transport = setup_tools.effective_transport(config, home=home)
    for item in setup_tools.tool_items(probe, transport=transport, environ=os.environ):
        checklist.add(item)
    for item in setup_identity.identity_items(config, home=home, is_confirmed_by_flag=yes):
        checklist.add(item)
    for item in setup_identity.gitignore_items(home, env=setup_git_env(os.environ)):
        checklist.add(item)
    typer.echo(summary_line(checklist.items))
    raise typer.Exit(setup_exit(checklist.items))
