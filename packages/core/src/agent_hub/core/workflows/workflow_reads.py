"""The registered hubs' workflows as hub web shows them: the list, a document and its layers.

``ReadWorkflows`` reads each hub's workflows on request through a ``WorkflowSource`` per hub
(``source_of``, the generator's discovery: the hub's ``workflows/``, then the built-ins) and
``check_workflows``, so an edited file shows on the next request. Each hub's read is kept with
the source's listing fingerprint (shown path, size and mtime of each entry) and reused while it
is unchanged.
With ``capture`` (AGH-295, D8, D14, A3), the list hands the capture every hub workflow that
loads and the detail its one workflow, each as the hub-relative file the discovery loaded
(``.yaml`` or ``.json``) marked with that file's own fingerprint entry, so an edit re-reads only
its file; one list request shares one capture budget across its hubs. A built-in has no unit,
and ``unit_of`` names a workflow's unit without capturing (``marked_workflow_unit`` with its
capture mark).
A file that does not load is a problem of the list, never an item, and its detail is not found.
A list scoped to an unknown project is empty; a detail of one raises ``EntityNotFoundError``.
"""

import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from agent_hub.core.item_versions.capture_item_versions import (
    CaptureBudget,
    CaptureItemVersions,
    UnitMark,
)
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.item_version_ports import MarkedUnit
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


# One listing entry: its path as ``WorkflowFile.file`` shows it, its size and mtime_ns.
type SourceStat = tuple[str, int, int]


class ListedWorkflowSource(WorkflowSource, Protocol):
    def fingerprint(self) -> tuple[SourceStat, ...]:
        """The listing's entries, stat only: it changes whenever a workflow file may have."""
        ...


class _Read(NamedTuple):
    catalog: WorkflowCatalog
    origins: dict[str, WorkflowOrigin]
    # Each hub-origin workflow file by name: the unit it is versioned in.
    files: dict[str, str]
    fingerprint: tuple[SourceStat, ...]
    # Each listed path's own fingerprint entry: a unit's capture mark.
    marks: dict[str, SourceStat]


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

    def __init__(
        self,
        hubs: ProjectHubs,
        source_of: Callable[[str], ListedWorkflowSource],
        *,
        capture: CaptureItemVersions | None = None,
    ) -> None:
        self._hubs = hubs
        self._source_of = source_of
        self._capture = capture
        self._memo: dict[str, _Read] = {}
        self._guard = threading.Lock()

    def list_workflows(self, scope: Scope) -> WorkflowCatalogView:
        items: list[WorkflowSummary] = []
        problems: list[WorkflowProblemView] = []
        budget = None if self._capture is None else self._capture.budget()
        for project, hub_path in self._hubs.project_hubs():
            if scope.project not in {None, project}:
                continue
            read = self._read(hub_path)
            catalog, origins = read.catalog, read.origins
            self._capture_plans(project, hub_path, read, *catalog.plans, budget=budget)
            items.extend(_summary(project, plan, origins) for plan in catalog.plans)
            problems.extend(
                WorkflowProblemView(project=project, **problem._asdict())
                for problem in catalog.problems
            )
        return WorkflowCatalogView(items=tuple(items), problems=tuple(problems))

    def get_workflow(self, project: str, name: str) -> WorkflowDetail:
        hub_path, plan = self.workflow_plan(project, name)
        read = self._read(hub_path)
        origins = read.origins
        self._capture_plans(project, hub_path, read, plan)
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
        catalog = self._read(hub_path).catalog
        plan = next((plan for plan in catalog.plans if plan.document.name == name), None)
        if plan is None:
            raise EntityNotFoundError(entity="workflow", entity_id=f"{project}/{name}")
        return hub_path, plan

    def unit_of(self, project: str, name: str) -> ItemUnit | None:
        """The unit the workflow is versioned in, or None (a built-in, D14); an unknown project
        or workflow is ``EntityNotFoundError``. Reads no unit."""
        marked = self.marked_workflow_unit(project, name)
        return None if marked is None else marked.unit

    def marked_workflow_unit(self, project: str, name: str) -> MarkedUnit | None:
        """``unit_of`` with the mark the reads capture the file under. Reads no unit."""
        hub_path, plan = self.workflow_plan(project, name)
        read = self._read(hub_path)
        unit = _unit_of(project, plan, read)
        if unit is None:
            return None
        mark = read.marks.get(unit.unit_path, read.fingerprint)
        return MarkedUnit(hub_path=hub_path, unit=unit, mark=mark, shared_by=1)

    def _capture_plans(
        self,
        project: str,
        hub_path: str,
        read: _Read,
        *plans: WorkflowPlan,
        budget: CaptureBudget | None = None,
    ) -> None:
        if self._capture is None:
            return
        marked: list[tuple[ItemUnit, UnitMark]] = []
        for plan in plans:
            unit = _unit_of(project, plan, read)
            if unit is not None:
                # A file the listing does not hold (never expected) falls back to the whole one.
                marked.append((unit, read.marks.get(unit.unit_path, read.fingerprint)))
        self._capture.capture(project, hub_path, marked, budget=budget)

    def _read(self, hub_path: str) -> _Read:
        source = self._source_of(hub_path)
        mark = source.fingerprint()
        with self._guard:
            found = self._memo.get(hub_path)
        if found is not None and found.fingerprint == mark:
            return found
        files = tuple(source.workflow_files())
        loaded = tuple(_workflow_files(files))
        origins = {item.stem: item.origin for item in loaded}
        hub_files = {item.stem: item.file for item in loaded if item.origin == "hub"}
        marks = {entry[0]: entry for entry in mark}
        read = _Read(check_workflows(_Listed(files)), origins, hub_files, mark, marks)
        with self._guard:
            self._memo[hub_path] = read
        return read


def _unit_of(project: str, plan: WorkflowPlan, read: _Read) -> ItemUnit | None:
    unit_path = read.files.get(plan.document.name)
    if unit_path is None:
        return None
    return ItemUnit(project=project, unit_path=unit_path, kind=UnitKind.WORKFLOW)


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
