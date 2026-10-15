"""The registered hubs' workflows as hub web shows them: the list, a document and its layers.

``ReadWorkflows`` reads each hub's workflows on request through a ``WorkflowSource`` per hub
(``source_of``, the generator's discovery: the hub's ``workflows/``, then the built-ins) and
``check_workflows``, so an edited file shows on the next request. Each hub's read is kept with
the source's listing fingerprint (path, size and mtime of each file) and reused while it is
unchanged; nothing is stored.
A file that does not load is a problem of the list, never an item, and its detail is not found.
A list scoped to an unknown project is empty; a detail of one raises ``EntityNotFoundError``.
"""

import threading
from collections.abc import Callable, Hashable, Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.readmodels.view_types import ViewModel
from agent_hub.core.workflows.catalog import (
    LoadProblem,
    WorkflowCatalog,
    WorkflowFile,
    WorkflowOrigin,
    WorkflowSource,
    check_workflows,
)
from agent_hub.core.workflows.plan import WorkflowPlan


class WorkflowNodeView(ViewModel):
    """A node as the graph shows it: its id, type and the nodes it waits for."""

    id: str
    type: str
    depends_on: tuple[str, ...]
    description: str | None = None


class WorkflowSummary(ViewModel):
    """A workflow of a project's hub, and where it comes from (``source``)."""

    project: str
    name: str
    description: str | None
    revision: int
    source: WorkflowOrigin
    node_count: int
    layer_count: int


class WorkflowDetail(WorkflowSummary):
    """A workflow's layers (in run order, nodes in declaration order) and its document as
    written (keys left out are not filled in)."""

    layers: tuple[tuple[WorkflowNodeView, ...], ...]
    document: dict[str, JsonValue]


class WorkflowProblemView(ViewModel):
    """Why a file of a project's hub is not a workflow: ``file`` is hub-relative (a built-in's
    starts ``<builtin>/``), ``line`` is 1-based when known, ``key`` is ``$`` for the file."""

    project: str
    file: str
    line: int | None
    key: str
    message: str


class WorkflowCatalogView(ViewModel):
    """The workflows that load, by project then name, and every problem found."""

    items: tuple[WorkflowSummary, ...]
    problems: tuple[WorkflowProblemView, ...]


class ListedWorkflowSource(WorkflowSource, Protocol):
    def fingerprint(self) -> Hashable:
        """A value that changes whenever a workflow file may have changed (stat only)."""
        ...


type _Read = tuple[WorkflowCatalog, dict[str, WorkflowOrigin]]


class ProjectHubs(Protocol):
    def project_hubs(self) -> Iterable[tuple[str, str]]:
        """Each valid registered project and its hub folder, the first registered of a name."""
        ...


class WorkflowReads(Protocol):
    """The workflow reads of hub web (``GET /workflows``)."""

    def list_workflows(self, scope: Scope) -> WorkflowCatalogView:
        """Every (or one) project's workflows and problems."""
        ...

    def get_workflow(self, project: str, name: str) -> WorkflowDetail:
        """One workflow that loads; ``EntityNotFoundError`` (``project``, ``workflow``) else."""
        ...


@dataclass(frozen=True)
class _Listed:
    files: tuple[WorkflowFile | LoadProblem, ...]

    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        return self.files


class ReadWorkflows:
    """``WorkflowReads`` over the registered hubs and a ``WorkflowSource`` per hub folder."""

    def __init__(self, hubs: ProjectHubs, source_of: Callable[[str], ListedWorkflowSource]) -> None:
        self._hubs = hubs
        self._source_of = source_of
        self._memo: dict[str, tuple[Hashable, _Read]] = {}
        self._guard = threading.Lock()

    def list_workflows(self, scope: Scope) -> WorkflowCatalogView:
        items: list[WorkflowSummary] = []
        problems: list[WorkflowProblemView] = []
        for project, hub_path in self._hubs.project_hubs():
            if scope.project not in {None, project}:
                continue
            catalog, origins = self._read(hub_path)
            items.extend(_summary(project, plan, origins) for plan in catalog.plans)
            problems.extend(
                WorkflowProblemView(project=project, **problem._asdict())
                for problem in catalog.problems
            )
        return WorkflowCatalogView(items=tuple(items), problems=tuple(problems))

    def get_workflow(self, project: str, name: str) -> WorkflowDetail:
        hub_path, plan = self.workflow_plan(project, name)
        _, origins = self._read(hub_path)
        nodes = {node.id: node for node in plan.document.nodes}
        layers = tuple(
            tuple(
                WorkflowNodeView(
                    id=node_id,
                    type=nodes[node_id].type,
                    depends_on=nodes[node_id].depends_on,
                    description=nodes[node_id].description,
                )
                for node_id in layer
            )
            for layer in plan.layers
        )
        document = plan.document.model_dump(mode="json", by_alias=True, exclude_unset=True)
        return WorkflowDetail(
            **_summary(project, plan, origins).model_dump(), layers=layers, document=document
        )

    def workflow_plan(self, project: str, name: str) -> tuple[str, WorkflowPlan]:
        """The project's hub folder and the plan of its workflow ``name`` (``WorkflowPlans``);
        ``EntityNotFoundError`` (``project``, ``workflow``) else."""
        hub_path = next(
            (path for known, path in self._hubs.project_hubs() if known == project), None
        )
        if hub_path is None:
            raise EntityNotFoundError(entity="project", entity_id=project)
        catalog, _ = self._read(hub_path)
        plan = next((plan for plan in catalog.plans if plan.document.name == name), None)
        if plan is None:
            raise EntityNotFoundError(entity="workflow", entity_id=f"{project}/{name}")
        return hub_path, plan

    def _read(self, hub_path: str) -> _Read:
        source = self._source_of(hub_path)
        mark = source.fingerprint()
        with self._guard:
            found = self._memo.get(hub_path)
        if found is not None and found[0] == mark:
            return found[1]
        files = tuple(source.workflow_files())
        origins = {item.stem: item.origin for item in _workflow_files(files)}
        read = check_workflows(_Listed(files)), origins
        with self._guard:
            self._memo[hub_path] = (mark, read)
        return read


def _workflow_files(files: Iterable[WorkflowFile | LoadProblem]) -> Iterator[WorkflowFile]:
    return (item for item in files if isinstance(item, WorkflowFile))


def _summary(
    project: str, plan: WorkflowPlan, origins: dict[str, WorkflowOrigin]
) -> WorkflowSummary:
    document = plan.document
    return WorkflowSummary(
        project=project,
        name=document.name,
        description=document.description,
        revision=document.revision,
        source=origins.get(document.name, "hub"),
        node_count=len(document.nodes),
        layer_count=len(plan.layers),
    )
