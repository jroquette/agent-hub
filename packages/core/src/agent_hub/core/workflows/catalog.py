"""The workflows a hub has, checked: what ``hub workflow list`` and ``validate`` print.

A ``WorkflowSource`` (the port) yields each file it read as a ``WorkflowFile``, its content
already parsed, or as a ``LoadProblem`` when the file could not be read. ``check_workflows``
loads and plans every file and gives each problem its file, line and key: the source's loader
records the line of each key path, so a problem is placed on the line of its nearest key.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal, NamedTuple, Protocol

from agent_hub.core.workflows.document import (
    Loc,
    WorkflowLoadError,
    WorkflowProblem,
    parse_workflow,
)
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow

# Where a workflow comes from: the hub's ``workflows/``, or the built-ins (ADR 0032).
type WorkflowOrigin = Literal["hub", "builtin"]
# The hub's folder of workflow packs, ``workflows/<pack>/``.
HUB_WORKFLOWS_FOLDER: Final = "workflows"


class LoadProblem(NamedTuple):
    """A file that does not load: where (``line`` is ``None`` when unknown), and why."""

    file: str
    line: int | None
    key: str
    message: str


@dataclass(frozen=True)
class WorkflowFile:
    """A workflow file as read: its shown name, stem, parsed content, the line of each key and
    where it comes from."""

    file: str
    stem: str
    content: object
    lines: Mapping[Loc, int] = field(default_factory=lambda: MappingProxyType({}))
    origin: WorkflowOrigin = "hub"

    def line_of(self, loc: Loc) -> int | None:
        """The line of ``loc``, or of its nearest enclosing key the loader recorded."""
        for end in range(len(loc), -1, -1):
            line = self.lines.get(loc[:end])
            if line is not None:
                return line
        return None

    def problem(self, problem: WorkflowProblem) -> LoadProblem:
        return LoadProblem(self.file, self.line_of(problem.loc), problem.key, problem.message)


class WorkflowSource(Protocol):
    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        """Every workflow file found, in a stable order, each read or refused."""
        ...


@dataclass(frozen=True)
class WorkflowCatalog:
    """The workflows that load, in the source's order, and every problem found."""

    plans: tuple[WorkflowPlan, ...]
    problems: tuple[LoadProblem, ...]


def check_workflows(source: WorkflowSource) -> WorkflowCatalog:
    """Load and plan every file of ``source``; a name is taken by its first file only."""
    plans: list[WorkflowPlan] = []
    problems: list[LoadProblem] = []
    names: dict[str, str] = {}
    for item in source.workflow_files():
        if isinstance(item, LoadProblem):
            problems.append(item)
            continue
        try:
            plan = plan_workflow(parse_workflow(item.content))
        except WorkflowLoadError as error:
            problems.extend(item.problem(problem) for problem in error.problems)
            continue
        name = plan.document.name
        if name != item.stem:
            message = f"must be the file's stem {item.stem!r}"
            problems.append(item.problem(WorkflowProblem(("name",), message)))
        elif name in names:
            message = f"the workflow {name!r} is already defined in {names[name]}"
            problems.append(item.problem(WorkflowProblem(("name",), message)))
        else:
            names[name] = item.file
            plans.append(plan)
    return WorkflowCatalog(tuple(plans), tuple(problems))
