"""``hub workflow list|validate``: the hub's workflows, loaded and planned (AGH-218).

The generator's ``discover_workflows`` finds the hub's ``workflows/<pack>/`` files, then the
built-ins (a hub workflow overrides a built-in of its name), through the strict YAML loader; core's
``check_workflows`` loads and plans each one. ``list`` prints one line per workflow that loads,
``<name>  <nodes> nodes  <description>``; ``validate [NAME]`` prints ``<name>: valid (<nodes> nodes
in <layers> layers)``. Each problem is one stderr line, ``<file>[:<line>]: <key>: <message>`` (the
key is ``$`` for a file that does not read), and any problem exits 1. A folder that is not a hub
exits 2. Nothing is written and no network is used.

``test [NAME]`` dry-runs each fixture of the discovered packs (or NAME's) in memory through the
engine (generator's ``run_fixtures``): one ``<file>: ok|FAILED`` line each, its problems and
warnings indented, then a count; a failed fixture exits 1. ``--stubs-init`` writes NAME's
skeleton fixture to ``<pack>/fixtures/<NAME>.yaml``, never over an existing file nor through a
linked folder, and notes when the skeleton's own dry run did not end ``done``.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.core.hub_config.problems import ROOT_PATH
from agent_hub.core.workflows.catalog import (
    LoadProblem,
    WorkflowCatalog,
    WorkflowFile,
    check_workflows,
)
from agent_hub.core.workflows.document import WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.engine import WorkflowEngineError
from agent_hub.core.workflows.plan import plan_workflow
from agent_hub.generator.workflow_discovery import (
    BUILTIN_WORKFLOWS,
    HUB_WORKFLOWS,
    WORKFLOW_SUFFIXES,
    WorkflowDiscovery,
    discover_workflows,
    pack_resolver,
)
from agent_hub.generator.workflow_fixtures import (
    FIXTURE_SUFFIX,
    FIXTURES,
    run_fixtures,
    skeleton_yaml,
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
                includes = pack_resolver(discovery, found.pack_root)
                shown = self._shown(found.path)
                yield WorkflowFile(shown, found.name, found.document, found.lines, includes)

    def _shown(self, path: Path) -> str:
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        if path.is_relative_to(self.builtin_root):
            return f"{BUILTIN_PREFIX}/{path.relative_to(self.builtin_root).as_posix()}"
        return str(path)


# ``hub workflow test`` (AGH-222): the packs' fixtures, dry-run in memory through the engine.


@workflow_app.command("test")
def test_workflows(
    name: Annotated[str | None, typer.Argument(help="Run only this workflow's fixtures.")] = None,
    *,
    stubs_init: Annotated[
        bool, typer.Option("--stubs-init", help="Write a skeleton fixture for NAME.")
    ] = False,
) -> None:
    """Run each pack's fixtures/*.yaml in memory, no child or event; exit 1 on a failure."""
    root = hub_root_or_exit(os.environ, command="workflow")
    discovery = discover_workflows(root, builtin_root=BUILTIN_WORKFLOWS)
    if stubs_init:
        _write_skeleton(root, discovery, name)
        return
    runs = run_fixtures(discovery, only=name)
    if name is not None and not runs:
        fail(f"no fixture for the workflow {name!r} in its pack's {FIXTURES}/")
    for fixture_run in runs:
        where = shown_text(_shown_fixture(root, fixture_run.path))
        typer.echo(f"{where}: {'FAILED' if fixture_run.problems else 'ok'}")
        for problem in fixture_run.problems:
            typer.echo(f"  {shown_text(problem)}")
        for warning in fixture_run.warnings:
            typer.echo(f"  warning: {shown_text(warning)}")
    failed = sum(1 for fixture_run in runs if fixture_run.problems)
    noun = "fixture" if len(runs) == 1 else "fixtures"
    typer.echo(f"{len(runs)} {noun}: {len(runs) - failed} passed, {failed} failed")
    if failed:
        raise typer.Exit(FAILURE)


def _write_skeleton(root: Path, discovery: WorkflowDiscovery, name: str | None) -> None:
    if name is None:
        fail("--stubs-init needs a workflow name")
    found = next((w for w in discovery.workflows if w.name == name), None)
    if found is None:
        fail(f"no workflow named {shown_path(name)} in {HUB_WORKFLOWS}/ or the built-ins")
    if found.origin != "hub":
        fail(f"{name!r} is a built-in workflow; its fixtures ship with it")
    try:
        includes = pack_resolver(discovery, found.pack_root)
        skeleton = skeleton_yaml(plan_workflow(parse_workflow(found.document), includes=includes))
    except (WorkflowLoadError, WorkflowEngineError) as error:
        fail(f"{_shown_fixture(root, found.path)}: {error}")
    target = _skeleton_target(root, found.pack_root, name)
    try:
        with target.open("x", encoding="utf-8") as file:
            file.write(skeleton.text)
    except FileExistsError:
        fail(f"{_shown_fixture(root, target)} already exists; it is not overwritten")
    except OSError as error:
        fail(f"{_shown_fixture(root, target)}: {error.strerror or error}")
    typer.echo(f"wrote {_shown_fixture(root, target)}")
    if skeleton.status != "done":
        typer.echo(
            f"note: its own dry run ended {skeleton.status}; fill in the stubs the placeholders"
            " could not satisfy"
        )


def _skeleton_target(root: Path, pack_root: Path, name: str) -> Path:
    """``<pack>/fixtures/<name>.yaml``, its folder made and checked: not a link, inside the pack."""
    folder = pack_root / FIXTURES
    if folder.is_symlink():
        fail(f"{_shown_fixture(root, folder)} is a link; nothing is written")
    try:
        folder.mkdir(exist_ok=True)
        inside = folder.resolve(strict=True).is_relative_to(pack_root.resolve(strict=True))
    except OSError as error:
        fail(f"{_shown_fixture(root, folder)}: {error.strerror or error}")
    if not inside or not folder.is_dir():
        fail(f"{_shown_fixture(root, folder)} is not a folder inside its pack; nothing is written")
    return folder / f"{name}{FIXTURE_SUFFIX}"


def _shown_fixture(root: Path, path: Path) -> str:
    return _DiscoveredSource(root, only=None, builtin_root=BUILTIN_WORKFLOWS)._shown(path)
