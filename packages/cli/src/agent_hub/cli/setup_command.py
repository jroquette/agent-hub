"""``hub setup``: onboard this machine for the hub, then list what is still missing.

The hub is ``AGENT_HUB_ROOT`` when ``./hub`` exports it, else the current folder; without a
``hub.json`` entry there the exit is 2. ``hub.json`` is read once: any problem with it, a pin
other than this release included (plan E1), prints the reader's lines and exits 1 before any
git call. Then the checklist, each item's lines printed as soon as it is decided (the
tools and the tracker credential, ``setup_tools``, then the developer's identity,
``setup_identity``, whose proposal and prompt alone go to stderr, whether git ignores
``hub.local.json`` when it exists, then each repo cloned or fetched next to the hub,
``setup_repos``, then ``hub doctor``'s check, run in process on the hub root whatever the
current folder, its findings under its totals), and the totals line ``setup: ...``; the exit
is 0 when every item is ``ok``, else 1.
"""

import os
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli import setup_identity, setup_repos, setup_tools
from agent_hub.cli.doctor_command import check_hub
from agent_hub.cli.doctor_report import finding_line, totals_line
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit, local_home
from agent_hub.cli.run_children import SESSION_HIDDEN, without
from agent_hub.core.doctor.run_rules import UsageProblem, count_findings, sort_findings
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.workspace.setup_checklist import (
    DOCTOR_FIX,
    ChecklistItem,
    State,
    doctor_item,
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
    for item in setup_identity.gitignore_items(home, env=setup_repos.setup_git_env(os.environ)):
        checklist.add(item)
    for item in setup_repos.repo_items(config, root=root, home=home, environ=os.environ):
        checklist.add(item)
    checklist.add(_doctor_item(root))
    typer.echo(summary_line(checklist.items))
    raise typer.Exit(setup_exit(checklist.items))


def _doctor_item(root: Path) -> ChecklistItem:
    """``hub doctor``'s check of the hub at ``root`` (its real path), as one checklist item."""
    run = check_hub(str(root))
    if isinstance(run, UsageProblem):  # pragma: no cover - unreachable: setup passes no --only
        # Only an ``--only`` selection is refused, and setup selects every rule.
        return ChecklistItem(
            state=State.MISSING, item="hub doctor", detail=one_line(run.message), fix=DOCTOR_FIX
        )
    findings = sort_findings(run.findings)
    totals = count_findings(findings)
    return doctor_item(
        totals=totals_line(totals),
        has_errors=totals.has_errors,
        finding_lines=[finding_line(finding) for finding in findings],
    )
