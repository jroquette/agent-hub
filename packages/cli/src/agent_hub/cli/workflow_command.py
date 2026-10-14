"""``hub workflow list|validate``: the hub's workflows, loaded and planned (AGH-218).

Each reads the hub's ``workflows/<pack>/<name>.json`` files through core's ``check_workflows``.
``list`` prints one line per workflow that loads, ``<name>  <nodes> nodes  <description>``;
``validate [NAME]`` prints ``<name>: valid (<nodes> nodes in <layers> layers)``. Each problem is
one stderr line, ``<file>[:<line>]: <key>: <message>``, and any problem exits 1. A folder that is
not a hub exits 2. Nothing is written and no network is used.

Only JSON is read for now: the strict YAML loader and discovery (built-ins, precedence by name)
are the generator's, and replace ``_JsonWorkflowSource`` when they land.
"""

import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_path
from agent_hub.core.hub_config.problems import ROOT_PATH, one_line
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes
from agent_hub.core.workflows.catalog import (
    LoadProblem,
    WorkflowCatalog,
    WorkflowFile,
    check_workflows,
)

WORKFLOWS_FOLDER: Final = "workflows"
# The strict loader's cap (docs/design/workflow-schema.md § Document and pack).
MAX_WORKFLOW_BYTES: Final = 256 * 1024

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
        fail(f"no workflow named {shown_path(name)} in {WORKFLOWS_FOLDER}/")
    for plan in catalog.plans:
        nodes, layers = len(plan.document.nodes), len(plan.layers)
        typer.echo(f"{plan.document.name}: valid ({nodes} nodes in {layers} layers)")
    _exit_on_problems(catalog)


def _catalog(*, name: str | None) -> WorkflowCatalog:
    root = hub_root_or_exit(os.environ, command="workflow")
    return check_workflows(_JsonWorkflowSource(root, only=name))


def _exit_on_problems(catalog: WorkflowCatalog) -> None:
    if catalog.problems:
        fail(*(_problem_line(problem) for problem in catalog.problems))


def _problem_line(problem: LoadProblem) -> str:
    where = shown_path(problem.file) + ("" if problem.line is None else f":{problem.line}")
    return f"{where}: {problem.key}: {problem.message}"


class _JsonWorkflowSource:
    """``workflows/<pack>/<stem>.json`` under the hub root, sorted; links are never followed."""

    def __init__(self, root: Path, *, only: str | None) -> None:
        self.root = root
        self.only = only

    def workflow_files(self) -> Iterator[WorkflowFile | LoadProblem]:
        folder = self.root / WORKFLOWS_FOLDER
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*/*.json")):
            if self.only is None or path.stem == self.only:
                yield self._read(path)

    def _read(self, path: Path) -> WorkflowFile | LoadProblem:
        shown = path.relative_to(self.root).as_posix()
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                return LoadProblem(
                    shown, None, ROOT_PATH, "not a regular file (links are never followed)"
                )
            content = path.read_bytes()
        except OSError as error:
            return LoadProblem(shown, None, ROOT_PATH, one_line(error.strerror or str(error)))
        if len(content) > MAX_WORKFLOW_BYTES:
            return LoadProblem(
                shown, None, ROOT_PATH, f"the file is over {MAX_WORKFLOW_BYTES} bytes"
            )
        try:
            value = load_json_bytes(content, strict=True)
        except InvalidJsonError as error:
            return LoadProblem(shown, error.line, ROOT_PATH, one_line(error.message))
        return WorkflowFile(shown, path.stem, value)
