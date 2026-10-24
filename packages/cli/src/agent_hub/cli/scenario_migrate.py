"""``hub scenario migrate``: graph-format scenarios (version 1) written again in place as blocks
(version 2) (ADR 0049; docs/design/scenarios.md § Tree format).

``plan_migration`` reads the hub's scenarios as ``hub scenario list`` does and gives, for each
scenario named (every version-1 scenario when none is), the canonical text of its tree (core's
``migrate_graph``, generator's ``render_document``), or why it cannot be migrated: no scenario
of that name (with the problems of a file of that name, if any), a file that does not load or
plan (its problems), one already at version 2, a JSON file (migrate rewrites
``scenarios/<pack>/<name>.yaml`` only), a file that is a link, or each node a tree cannot hold.
A folder's problem (a linked ``scenarios/`` or pack folder) refuses a run with no names, which
cannot read every scenario.

``write_migration`` writes one file through the generator's hub item writer: a temporary file
beside it, then a rename, each folder on the way opened with ``O_NOFOLLOW``, so nothing is
written through a link. The file's revision is kept and no git command runs.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.cli.init_report import shown_path
from agent_hub.cli.workflow_command import problem_line
from agent_hub.cli.workflow_runs import WorkflowRunError
from agent_hub.core.item_versions.hub_item_writer import HubItemWriteError, ItemWriteRefusedError
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.scenarios.tree_migrate import (
    ALREADY_A_TREE,
    MigrationError,
    migrate_graph,
    stage_name,
)
from agent_hub.core.scenarios.tree_translate import block_map
from agent_hub.core.workflows.catalog import LoadProblem, check_workflows
from agent_hub.core.workflows.document import WorkflowLoadError, is_tree
from agent_hub.generator.hub_item_writer import FileSystemHubItemWriter
from agent_hub.generator.scenario_discovery import HUB_SCENARIOS, DiscoveredScenarioSource
from agent_hub.generator.scenario_yaml import render_document
from agent_hub.generator.workflow_discovery import WORKFLOW_SUFFIXES, DiscoveredWorkflow
from agent_hub.generator.workflow_yaml import JSON_SUFFIX

GRAPH_VERSION: Final = 1
_LINKED: Final = "it is a link: migrate writes the file in place, never through a link"


@dataclass(frozen=True, kw_only=True)
class Migrated:
    """A scenario's tree: its file (relative to the hub), name, stage, block count and text."""

    file: str
    name: str
    stage: str
    blocks: int
    text: str


@dataclass(frozen=True, kw_only=True)
class Refused:
    """Why a scenario (``name``; ``None`` for a folder's problem) cannot be migrated, as lines."""

    name: str | None
    lines: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class MigrationPlan:
    """What a migrate would write, and what it refuses: with any refusal it writes nothing."""

    migrated: tuple[Migrated, ...]
    refused: tuple[Refused, ...]


def plan_migration(hub: Path, names: Sequence[str]) -> MigrationPlan:
    """The trees of the scenarios ``names`` (every version-1 one when empty), or why not."""
    source = DiscoveredScenarioSource(hub)
    catalog = check_workflows(source)
    planned = {plan.document.name for plan in catalog.plans}
    on_folders = [problem for problem in catalog.problems if not _of_a_file(problem)]
    refused: list[Refused] = []
    if not names and on_folders:
        refused.append(Refused(name=None, lines=tuple(map(problem_line, on_folders))))
    wanted = list(dict.fromkeys(names)) or [
        name for name, found in sorted(source.found.items()) if _is_graph(found.document)
    ]
    migrated: list[Migrated] = []
    for name in wanted:
        found = source.found.get(name)
        on_file = [p for p in catalog.problems if _of_a_file(p) and Path(p.file).stem == name]
        if found is None:
            missing = f"no scenario named {shown_path(name)} in {HUB_SCENARIOS}/"
            lines = (*map(problem_line, on_file or on_folders), missing)
            refused.append(Refused(name=name, lines=lines))
            continue
        outcome = _migrated(hub, found, on_file, loads=name in planned)
        if isinstance(outcome, Refused):
            refused.append(outcome)
        else:
            migrated.append(outcome)
    return MigrationPlan(migrated=tuple(migrated), refused=tuple(refused))


def write_migration(hub: Path, migrated: Migrated) -> None:
    """Write ``migrated``'s file in place, never through a link; else ``WorkflowRunError``."""
    content = UnitContent(
        files=(UnitFile(path=Path(migrated.file).name, content=migrated.text.encode()),)
    )
    try:
        FileSystemHubItemWriter().write_unit(
            str(hub), migrated.file, content, kind=UnitKind.SCENARIO
        )
    except ItemWriteRefusedError as error:
        raise WorkflowRunError(f"cannot write {migrated.file}: {error.reason}") from None
    except (HubItemWriteError, OSError) as error:
        cause = error.cause if isinstance(error, HubItemWriteError) else error.strerror
        raise WorkflowRunError(f"cannot write {migrated.file}: {cause or error}") from None


def _migrated(
    hub: Path, found: DiscoveredWorkflow, on_file: list[LoadProblem], *, loads: bool
) -> Migrated | Refused:
    file = found.path.relative_to(hub).as_posix()
    shown = shown_path(file)

    def refused(*reasons: str) -> Refused:
        return Refused(name=found.name, lines=tuple(f"{shown}: {reason}" for reason in reasons))

    if is_tree(found.document):
        return refused(ALREADY_A_TREE)
    if found.path.suffix == JSON_SUFFIX:
        target = shown_path(f"{found.name}.yaml")
        return refused(
            f"it is a JSON file: migrate rewrites a .yaml file in place; rename it to {target}"
            " first"
        )
    if found.path.is_symlink():
        return refused(_LINKED)
    if not loads:
        return Refused(name=found.name, lines=tuple(map(problem_line, on_file)))
    try:
        tree = migrate_graph(found.document)
    except MigrationError as error:
        return refused(*map(str, error.problems))
    except WorkflowLoadError as error:
        return refused(str(error))
    stage = stage_name(found.name)
    blocks = sum(1 for block in block_map(tree).blocks if block.kind != "stage")
    return Migrated(
        file=file, name=found.name, stage=stage, blocks=blocks, text=render_document(tree)
    )


def _of_a_file(problem: LoadProblem) -> bool:
    """Whether ``problem`` is a file's, not a folder's (a linked folder, the file budget)."""
    return Path(problem.file).suffix in WORKFLOW_SUFFIXES


def _is_graph(document: object) -> bool:
    if not isinstance(document, dict):
        return False
    version = document.get("version")
    return type(version) is int and version == GRAPH_VERSION
