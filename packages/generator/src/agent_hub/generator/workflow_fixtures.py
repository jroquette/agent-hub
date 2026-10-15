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

# Private helpers of workflow_discovery, kept unrenamed while their module is in other open PRs.
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
MAX_PACK_FIXTURES: Final = 50


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


@dataclass(frozen=True, kw_only=True, slots=True)
class Skeleton:
    """A skeleton fixture's YAML and the status its own dry run ended with."""

    text: str
    status: str


def pack_fixtures(pack_root: Path) -> tuple[FixtureFile | WorkflowFileError, ...]:
    """Each ``fixtures/*.yaml`` of the pack, by name, at most ``MAX_PACK_FIXTURES`` (then one
    problem); a missing folder reads as empty."""
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
        if len(found) == MAX_PACK_FIXTURES:
            reason = f"more than {MAX_PACK_FIXTURES} fixture files; the rest is not read"
            found.append(WorkflowFileError(source=str(folder), line=None, reason=reason))
            break
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
        # With ``only``, a file whose target cannot be read belongs to that workflow's pack.
        in_scope = only is None or only in workflows
        for item in pack_fixtures(pack_root):
            if isinstance(item, WorkflowFileError):
                if in_scope:
                    problem = _line_reason(item)
                    runs.append(
                        FixtureRun(path=Path(item.source), workflow=None, problems=(problem,))
                    )
            elif _wanted(item.document.get("workflow"), workflows, overridden, only=only):
                runs.append(_run_one(item, workflows))
    return tuple(runs)


def _wanted(
    target: object,
    workflows: dict[str, DiscoveredWorkflow],
    overridden: set[str],
    *,
    only: str | None,
) -> bool:
    """Whether a fixture for ``target`` runs: a non-text target fails it in its pack's scope."""
    if not isinstance(target, str):
        return only is None or only in workflows
    # A fixture of a built-in the hub overrides belongs to a workflow that is not run.
    shadowed = target in overridden and target not in workflows
    return not shadowed and (only is None or target == only)


def skeleton_yaml(plan: WorkflowPlan) -> Skeleton:
    """A fixture for ``plan`` (core's ``skeleton_fixture``) as YAML, and how its run ended."""
    skeleton = skeleton_fixture(plan, outputs=JsonSchemaOutputs())
    expect = skeleton["expect"]
    status = expect.get("status") if isinstance(expect, dict) else None
    text = yaml.safe_dump(skeleton, sort_keys=False, allow_unicode=True)
    return Skeleton(text=text, status=str(status))


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
