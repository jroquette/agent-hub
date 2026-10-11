"""``hub setup``: onboard this machine for the hub, then list what is still missing.

The hub is ``AGENT_HUB_ROOT`` when ``./hub`` exports it, else the current folder; without a
``hub.json`` entry there the exit is 2. ``hub.json`` is read once: any problem with it, a pin
other than this release included (plan E1), prints the reader's lines and exits 1 before any
git call. Then the checklist, each item's lines printed as soon as it is decided, and the totals
line ``setup: ...``; the exit is 0 when every item is ``ok``, else 1.
"""

import os
from typing import Annotated, Final

import typer

from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit
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
    load_hub_config_or_exit(root / FILE_LABEL)
    checklist = Checklist()
    typer.echo(summary_line(checklist.items))
    raise typer.Exit(setup_exit(checklist.items))
