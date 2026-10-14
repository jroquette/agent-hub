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
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_path
from agent_hub.core.hub_config.problems import ROOT_PATH
from agent_hub.core.workflows.catalog import (
    LoadProblem,
    WorkflowCatalog,
    WorkflowFile,
    check_workflows,
)
from agent_hub.generator.workflow_discovery import (
    BUILTIN_WORKFLOWS,
    HUB_WORKFLOWS,
    WORKFLOW_SUFFIXES,
    discover_workflows,
)

# How a built-in's file is shown: it lives in the installed package, not in the hub.
BUILTIN_PREFIX: Final = "<builtin>"

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
    return check_workflows(_DiscoveredSource(root, only=name, builtin_root=BUILTIN_WORKFLOWS))


def _exit_on_problems(catalog: WorkflowCatalog) -> None:
    if catalog.problems:
        fail(*(_problem_line(problem) for problem in catalog.problems))


def _problem_line(problem: LoadProblem) -> str:
    where = shown_path(problem.file) + ("" if problem.line is None else f":{problem.line}")
    return f"{where}: {problem.key}: {problem.message}"


class _DiscoveredSource:
    """The ``WorkflowSource`` over the generator's discovery; ``only`` keeps one name's files."""

    def __init__(self, root: Path, *, only: str | None, builtin_root: Path) -> None:
        self.root = root
        self.only = only
        self.builtin_root = builtin_root

    def workflow_files(self) -> Iterator[WorkflowFile | LoadProblem]:
        discovery = discover_workflows(self.root, builtin_root=self.builtin_root)
        for problem in discovery.problems:
            # A folder's problem (a linked workflows/, an unreadable pack, the file budget)
            # bears on every name; a file's only on its own.
            on_folder = problem.path.suffix not in WORKFLOW_SUFFIXES
            if self.only is None or on_folder or problem.path.stem == self.only:
                yield LoadProblem(
                    self._shown(problem.path), problem.line, ROOT_PATH, problem.reason
                )
        for found in discovery.workflows:
            if self.only is None or found.name == self.only:
                yield WorkflowFile(self._shown(found.path), found.name, found.document, found.lines)

    def _shown(self, path: Path) -> str:
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        if path.is_relative_to(self.builtin_root):
            return f"{BUILTIN_PREFIX}/{path.relative_to(self.builtin_root).as_posix()}"
        return str(path)
