"""``hub workflow list|validate``: the hub's workflows, loaded and planned (AGH-218).

The generator's ``discover_workflows`` finds the hub's ``workflows/<pack>/`` files, then the
built-ins (a hub workflow overrides a built-in of its name), through the strict YAML loader; core's
``check_workflows`` loads and plans each one. ``list`` prints one line per workflow that loads,
``<name>  <nodes> nodes  <description>``; ``validate [NAME]`` prints ``<name>: valid (<nodes> nodes
in <layers> layers)``. Each problem is one stderr line, ``<file>[:<line>]: <key>: <message>`` (the
key is ``$`` for a file that does not read), and any problem exits 1. A folder that is not a hub
exits 2. Nothing is written and no network is used.
"""

import os
from typing import Annotated

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_path
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowCatalog, check_workflows
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, HUB_WORKFLOWS
from agent_hub.generator.workflow_source import DiscoveredWorkflowSource

workflow_app = typer.Typer(name="workflow", no_args_is_help=True, help="List and check workflows.")


@workflow_app.command("list")
def list_workflows() -> None:
    """List the hub's workflows; a file that does not load is one stderr line."""
    catalog = _catalog(name=None)
    for plan in catalog.plans:
        document = plan.document
        typer.echo(
            f"{document.name}  {len(document.nodes)} nodes  {document.description or ''}".rstrip()
        )
    _exit_on_problems(catalog)


@workflow_app.command("validate")
def validate(
    name: Annotated[str | None, typer.Argument(help="Check only this workflow.")] = None,
) -> None:
    """Load and plan the hub's workflows (or one): every problem, one per line."""
    catalog = _catalog(name=name)
    if name is not None and not catalog.plans and not catalog.problems:
        fail(f"no workflow named {shown_path(name)} in {HUB_WORKFLOWS}/ or the built-ins")
    for plan in catalog.plans:
        nodes, layers = len(plan.document.nodes), len(plan.layers)
        typer.echo(f"{plan.document.name}: valid ({nodes} nodes in {layers} layers)")
    _exit_on_problems(catalog)


def _catalog(*, name: str | None) -> WorkflowCatalog:
    root = hub_root_or_exit(os.environ, command="workflow")
    return check_workflows(
        DiscoveredWorkflowSource(root, only=name, builtin_root=BUILTIN_WORKFLOWS)
    )


def _exit_on_problems(catalog: WorkflowCatalog) -> None:
    if catalog.problems:
        fail(*(_problem_line(problem) for problem in catalog.problems))


def _problem_line(problem: LoadProblem) -> str:
    where = shown_path(problem.file) + ("" if problem.line is None else f":{problem.line}")
    return f"{where}: {problem.key}: {problem.message}"
