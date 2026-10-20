"""``hub scenario list|plan``: the hub's scenarios, listed and planned
(docs/design/scenarios.md § Contract, § Plan and modes; ADR 0041).

``list`` prints one line per scenario that loads, ``<name>  <pack>  <nodes> nodes
[<description>]``; each problem is one stderr line, ``<file>[:<line>]: <key>: <message>``, and
exits 1; a hub without scenarios prints ``no scenarios yet``. Scenarios live in
``scenarios/<pack>/`` only: ``hub workflow list`` never shows one.
"""

import os
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.workflow_command import problem_line
from agent_hub.core.workflows.catalog import WorkflowCatalog, check_workflows
from agent_hub.generator.scenario_discovery import DiscoveredScenarioSource

COMMAND: Final = "scenario"

scenario_app = typer.Typer(
    name=COMMAND, no_args_is_help=True, help="List and plan the hub's scenarios."
)


@scenario_app.command("list")
def list_command() -> None:
    """List every scenario with its pack, node count and description."""
    source = DiscoveredScenarioSource(_hub())
    catalog = check_workflows(source)
    if not catalog.plans and not catalog.problems:
        typer.echo("no scenarios yet")
    for plan in catalog.plans:
        document = plan.document
        pack = source.found[document.name].pack
        line = f"{document.name}  {pack}  {len(document.nodes)} nodes"
        typer.echo(f"{line}  {document.description}" if document.description else line)
    _exit_on_problems(catalog)


def _hub() -> Path:
    return hub_root_or_exit(os.environ, command=COMMAND)


def _exit_on_problems(catalog: WorkflowCatalog) -> None:
    if catalog.problems:
        fail(*(problem_line(problem) for problem in catalog.problems))
