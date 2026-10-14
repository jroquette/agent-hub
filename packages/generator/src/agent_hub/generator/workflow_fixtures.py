"""Run the fixtures of discovered workflow packs (docs/design/workflow-schema.md § Dry run).

``pack_fixtures`` reads each ``<pack>/fixtures/*.yaml`` as a workflow file is read: the strict
loader (its caps, refusals and key lines), the real path inside the pack, a regular file.
``run_fixtures`` runs every fixture of the packs a discovery found (or those of one workflow)
through core's ``run_fixture`` with the JSON Schema ``OutputValidator``: in memory, no child, no
network, no event. A fixture runs against the workflow its ``workflow`` names in its own pack; one
for a built-in that the hub overrides is not run. A file that does not load, a fixture that does
not parse, a workflow that is not in the pack or does not plan is a failed result, never a crash.
``skeleton_yaml`` is the text ``hub workflow test --stubs-init`` writes.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from agent_hub.core.workflows.catalog import WorkflowFile
from agent_hub.core.workflows.document import WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.fixtures import parse_fixture, run_fixture, skeleton_fixture
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.generator.workflow_discovery import (
    DiscoveredWorkflow,
    WorkflowDiscovery,
    _cause,
    _load,
)
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import KeyPath, WorkflowFileError, WorkflowMapping

FIXTURES: Final = "fixtures"
FIXTURE_SUFFIX: Final = ".yaml"


@dataclass(frozen=True, kw_only=True, slots=True)
class FixtureFile:
    """A fixture file's mapping and the 1-based line of each key path."""

    path: Path
    document: WorkflowMapping
    lines: dict[KeyPath, int]


@dataclass(frozen=True, kw_only=True, slots=True)
class FixtureRun:
    """One fixture file's result: ``problems`` fail it, ``warnings`` do not."""

    path: Path
    workflow: str | None
    problems: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def pack_fixtures(pack_root: Path) -> tuple[FixtureFile | WorkflowFileError, ...]:
    """Each ``fixtures/*.yaml`` of the pack, by name; a missing folder reads as empty."""
    folder = pack_root / FIXTURES
    if folder.is_symlink():
        reason = "the fixtures folder is a link; it is not read"
        return (WorkflowFileError(source=str(folder), line=None, reason=reason),)
    try:
        with os.scandir(folder) as listing:
            names = sorted(entry.name for entry in listing if not entry.name.startswith("."))
    except FileNotFoundError, NotADirectoryError:
        return ()
    except OSError as error:
        return (WorkflowFileError(source=str(folder), line=None, reason=_cause(error)),)
    found: list[FixtureFile | WorkflowFileError] = []
    for name in names:
        path = folder / name
        if path.suffix != FIXTURE_SUFFIX:
            continue
        loaded = _load(pack_root, path)
        if isinstance(loaded, WorkflowFileError):
            found.append(loaded)
        else:
            found.append(FixtureFile(path=path, document=loaded.document, lines=dict(loaded.lines)))
    return tuple(found)


def run_fixtures(
    discovery: WorkflowDiscovery, *, only: str | None = None
) -> tuple[FixtureRun, ...]:
    """Run the fixtures of every pack ``discovery`` found, or only those for ``only``."""
    overridden = {workflow.name for workflow in discovery.overridden}
    packs: dict[Path, dict[str, DiscoveredWorkflow]] = {}
    for workflow in discovery.workflows:
        packs.setdefault(workflow.pack_root, {})[workflow.name] = workflow
    runs: list[FixtureRun] = []
    for pack_root, workflows in packs.items():
        for item in pack_fixtures(pack_root):
            if isinstance(item, WorkflowFileError):
                problem = _line_reason(item)
                runs.append(FixtureRun(path=Path(item.source), workflow=None, problems=(problem,)))
                continue
            target = item.document.get("workflow")
            # A fixture of a built-in the hub overrides belongs to a workflow that is not run.
            shadowed = target in overridden and target not in workflows
            if not shadowed and (only is None or target == only):
                runs.append(_run_one(item, workflows))
    return tuple(runs)


def skeleton_yaml(plan: WorkflowPlan) -> str:
    """A passing fixture for ``plan`` (core's ``skeleton_fixture``) as YAML."""
    skeleton = skeleton_fixture(plan, outputs=JsonSchemaOutputs())
    return yaml.safe_dump(skeleton, sort_keys=False, allow_unicode=True)


def _run_one(item: FixtureFile, workflows: dict[str, DiscoveredWorkflow]) -> FixtureRun:
    shown = WorkflowFile(str(item.path), item.path.stem, item.document, item.lines)
    try:
        fixture = parse_fixture(item.document)
    except WorkflowLoadError as error:
        problems = tuple(_located(shown.problem(problem)) for problem in error.problems)
        return FixtureRun(path=item.path, workflow=None, problems=problems)
    found = workflows.get(fixture.workflow)
    if found is None:
        problem = f"workflow: no workflow named {fixture.workflow!r} in this pack"
        return FixtureRun(path=item.path, workflow=fixture.workflow, problems=(problem,))
    try:
        plan = plan_workflow(parse_workflow(found.document))
    except WorkflowLoadError:
        problem = f"the workflow {fixture.workflow!r} does not load (hub workflow validate)"
        return FixtureRun(path=item.path, workflow=fixture.workflow, problems=(problem,))
    result = run_fixture(plan, fixture, outputs=JsonSchemaOutputs())
    return FixtureRun(
        path=item.path,
        workflow=fixture.workflow,
        problems=result.problems,
        warnings=result.warnings,
    )


def _located(problem: tuple[str, int | None, str, str]) -> str:
    _, line, key, message = problem
    return f"{key}: {message}" if line is None else f"line {line}: {key}: {message}"


def _line_reason(error: WorkflowFileError) -> str:
    return error.reason if error.line is None else f"line {error.line}: {error.reason}"
