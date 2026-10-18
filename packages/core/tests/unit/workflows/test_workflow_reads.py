"""The workflows of the registered hubs as the API serves them: list, layers, source (AC-213.15)."""

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest

from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.core.testing.item_version_fakes import InMemoryItemVersionStore
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile
from agent_hub.core.workflows.workflow_reads import ReadWorkflows, SourceStat

SHIP = {
    "version": 1,
    "name": "ship",
    "description": "Build, then lint and test, then deploy",
    "revision": 2,
    "nodes": [
        {"id": "build", "type": "shell", "command": ["make", "build"]},
        {"id": "lint", "type": "shell", "command": ["make", "lint"], "depends_on": ["build"]},
        {"id": "test", "type": "shell", "command": ["make", "test"], "depends_on": ["build"]},
        {
            "id": "deploy",
            "type": "agent",
            "prompt": "Deploy it",
            "depends_on": ["lint", "test"],
        },
    ],
}
BROKEN = {"version": 1, "name": "broken", "revision": 1, "nodes": [{"id": "a", "type": "nope"}]}


class Hubs:
    def __init__(self, *hubs: tuple[str, str]) -> None:
        self.hubs = hubs

    def project_hubs(self) -> Iterable[tuple[str, str]]:
        return self.hubs


class Files:
    """``mark`` stands for the listing's other entries (a pack folder), ``stamps`` for each
    workflow file's mtime."""

    def __init__(self, items: tuple[WorkflowFile | LoadProblem, ...], mark: int = 1) -> None:
        self.items = items
        self.mark = mark
        self.stamps: dict[str, int] = {}
        self.reads = 0

    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        self.reads += 1
        return self.items

    def fingerprint(self) -> tuple[SourceStat, ...]:
        files = [item.file for item in self.items if isinstance(item, WorkflowFile)]
        stats = tuple((file, 1, self.stamps.get(file, 0)) for file in files)
        return (("workflows", 0, self.mark), *stats)


def reads() -> ReadWorkflows:
    files = {
        "/hubs/demo": (
            WorkflowFile("workflows/demo/ship.yaml", "ship", SHIP),
            WorkflowFile("workflows/demo/broken.yaml", "broken", BROKEN, {("nodes", 0): 7}),
        ),
        "/hubs/other": (
            WorkflowFile("<builtin>/base/ship.yaml", "ship", SHIP, origin="builtin"),
            LoadProblem("workflows", None, "$", "the workflows folder is a link; it is not read"),
        ),
    }
    return ReadWorkflows(
        Hubs(("demo", "/hubs/demo"), ("other", "/hubs/other")),
        lambda hub_path: Files(files[hub_path]),
    )


def test_lists_each_project_workflow_and_problem_when_hubs_registered() -> None:
    catalog = reads().list_workflows(Scope())

    assert [(item.project, item.name, item.source) for item in catalog.items] == [
        ("demo", "ship", "hub"),
        ("other", "ship", "builtin"),
    ]
    ship = catalog.items[0]
    assert (ship.description, ship.revision, ship.node_count, ship.layer_count) == (
        "Build, then lint and test, then deploy",
        2,
        4,
        3,
    )
    assert [(p.project, p.file, p.line, p.key) for p in catalog.problems] == [
        ("demo", "workflows/demo/broken.yaml", 7, "nodes[0].type"),
        ("other", "workflows", None, "$"),
    ]


def test_lists_one_project_when_scope_names_it() -> None:
    catalog = reads().list_workflows(Scope(project="other"))

    assert [item.project for item in catalog.items] == ["other"]
    assert reads().list_workflows(Scope(project="unknown")).items == ()


def test_gives_layers_and_document_when_workflow_requested() -> None:
    detail = reads().get_workflow("demo", "ship")

    assert [[node.id for node in layer] for layer in detail.layers] == [
        ["build"],
        ["lint", "test"],
        ["deploy"],
    ]
    deploy = detail.layers[2][0]
    assert (deploy.type, deploy.depends_on) == ("agent", ("lint", "test"))
    assert detail.document == SHIP
    assert (detail.source, detail.project) == ("hub", "demo")


@pytest.mark.parametrize(
    ("project", "name", "entity"),
    [("demo", "broken", "workflow"), ("demo", "nope", "workflow"), ("nope", "ship", "project")],
)
def test_raises_not_found_when_workflow_or_project_unknown(
    project: str, name: str, entity: str
) -> None:
    with pytest.raises(EntityNotFoundError) as raised:
        reads().get_workflow(project, name)

    assert raised.value.entity == entity


def test_reads_hub_files_once_when_listing_fingerprint_unchanged() -> None:
    files = Files((WorkflowFile("workflows/demo/ship.yaml", "ship", SHIP),))
    reads = ReadWorkflows(Hubs(("demo", "/hubs/demo")), lambda _hub: files)

    reads.list_workflows(Scope())
    reads.get_workflow("demo", "ship")
    files.mark = 2
    changed = reads.list_workflows(Scope())

    assert files.reads == 2
    assert [item.name for item in changed.items] == ["ship"]


def test_gives_hub_and_plan_when_workflow_plan_asked() -> None:
    hub_path, plan = reads().workflow_plan("demo", "ship")

    assert (hub_path, plan.document.name, len(plan.layers)) == ("/hubs/demo", "ship", 3)


SHIP_FILE = "workflows/demo/ship.yaml"


def _capturing(
    *items: WorkflowFile | LoadProblem, disk: dict[str, bytes]
) -> tuple[ReadWorkflows, Files, FakeHubFileReader, InMemoryItemVersionStore]:
    files = Files(items)
    reader = FakeHubFileReader({"/hubs/demo": FakeHub(skill_files=dict(disk))})
    store = InMemoryItemVersionStore()
    capture = CaptureItemVersions(store, reader, lambda: datetime(2026, 10, 18, tzinfo=UTC))
    reads = ReadWorkflows(Hubs(("demo", "/hubs/demo")), lambda _hub: files, capture=capture)
    return reads, files, reader, store


def test_reads_one_budget_when_unscoped_list_spans_hubs() -> None:
    disk = {SHIP_FILE: b"name: ship\n" * 10}
    budget = len(disk[SHIP_FILE])
    reader = FakeHubFileReader(
        {"/hubs/one": FakeHub(skill_files=dict(disk)), "/hubs/two": FakeHub(skill_files=dict(disk))}
    )
    capture = CaptureItemVersions(
        InMemoryItemVersionStore(),
        reader,
        lambda: datetime(2026, 10, 18, tzinfo=UTC),
        budget_bytes=budget,
    )
    files = Files((WorkflowFile(SHIP_FILE, "ship", SHIP),))
    reads = ReadWorkflows(
        Hubs(("one", "/hubs/one"), ("two", "/hubs/two")), lambda _hub: files, capture=capture
    )

    reads.list_workflows(Scope())

    # The first hub's read spends the request's budget; the second waits for a later read.
    assert reader.unit_reads == [("/hubs/one", SHIP_FILE)]
    reads.list_workflows(Scope())
    assert reader.unit_reads == [("/hubs/one", SHIP_FILE), ("/hubs/two", SHIP_FILE)]


def test_rereads_only_edited_file_when_one_of_two_hub_workflows_changes() -> None:
    lint = {**SHIP, "name": "lint"}
    lint_file = "workflows/demo/lint.yaml"
    reads, files, reader, _ = _capturing(
        WorkflowFile(SHIP_FILE, "ship", SHIP),
        WorkflowFile(lint_file, "lint", lint),
        disk={SHIP_FILE: b"name: ship\n", lint_file: b"name: lint\n"},
    )
    reads.list_workflows(Scope())
    reader.unit_reads.clear()

    files.stamps[lint_file] = 1
    reads.list_workflows(Scope())

    assert reader.unit_reads == [("/hubs/demo", lint_file)]


def test_captures_hub_files_when_listed() -> None:
    reads, files, reader, store = _capturing(
        WorkflowFile(SHIP_FILE, "ship", SHIP),
        WorkflowFile("workflows/demo/broken.yaml", "broken", BROKEN),
        disk={SHIP_FILE: b"name: ship\n", "workflows/demo/broken.yaml": b"name: broken\n"},
    )

    reads.list_workflows(Scope())
    reads.list_workflows(Scope())
    reads.get_workflow("demo", "ship")
    files.stamps[SHIP_FILE] = 1
    reads.get_workflow("demo", "ship")

    assert reader.unit_reads == [("/hubs/demo", SHIP_FILE), ("/hubs/demo", SHIP_FILE)]
    last = store.last("demo", SHIP_FILE)
    assert last is not None
    assert (last.seq, last.first, last.kind) == (1, True, UnitKind.WORKFLOW)
    assert store.last("demo", "workflows/demo/broken.yaml") is None
    assert reads.unit_of("demo", "ship") == ItemUnit(
        project="demo", unit_path=SHIP_FILE, kind=UnitKind.WORKFLOW
    )


def test_no_unit_when_workflow_builtin() -> None:
    reads, _, reader, store = _capturing(
        WorkflowFile("<builtin>/base/ship.yaml", "ship", SHIP, origin="builtin"), disk={}
    )

    reads.list_workflows(Scope())
    reads.get_workflow("demo", "ship")

    assert reads.unit_of("demo", "ship") is None
    assert reader.unit_reads == []
    with pytest.raises(EntityNotFoundError):
        reads.unit_of("demo", "nope")
    assert store.last("demo", "<builtin>/base/ship.yaml") is None


def test_versions_json_file_when_json_workflow() -> None:
    json_file = "workflows/demo/ship.json"
    reads, _, _, store = _capturing(
        WorkflowFile(json_file, "ship", SHIP), disk={json_file: b'{"name": "ship"}\n'}
    )

    reads.get_workflow("demo", "ship")

    last = store.last("demo", json_file)
    assert last is not None
    assert (last.kind, last.size) == (UnitKind.WORKFLOW, len(b'{"name": "ship"}\n'))


def test_marks_workflow_unit_as_detail_captures_when_hub_file() -> None:
    reads, files, reader, _ = _capturing(
        WorkflowFile(SHIP_FILE, "ship", SHIP), disk={SHIP_FILE: b"x"}
    )
    reads.get_workflow("demo", "ship")

    marked = reads.marked_workflow_unit("demo", "ship")

    assert marked is not None
    assert (marked.hub_path, marked.unit.unit_path, marked.shared_by) == (
        "/hubs/demo",
        SHIP_FILE,
        1,
    )
    # The file's own fingerprint entry, as the detail captures it under.
    assert marked.mark in files.fingerprint()
    assert len(reader.unit_reads) == 1
