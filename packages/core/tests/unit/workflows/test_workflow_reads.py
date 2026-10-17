"""The workflows of the registered hubs as the API serves them: list, layers, source (AC-213.15)."""

from collections.abc import Iterable

import pytest

from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile
from agent_hub.core.workflows.workflow_reads import ReadWorkflows

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
    def __init__(self, items: tuple[WorkflowFile | LoadProblem, ...], mark: object = 1) -> None:
        self.items = items
        self.mark = mark
        self.reads = 0

    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        self.reads += 1
        return self.items

    def fingerprint(self) -> object:
        return self.mark


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


def test_counts_steps_by_type_and_lists_inputs_when_listed() -> None:
    rounds = {
        "version": 1,
        "name": "rounds",
        "revision": 1,
        "inputs": {
            "issue": {"required": True, "description": "The issue"},
            "tries": {"type": "integer", "default": 2},
        },
        "nodes": [
            {"id": "prep", "type": "shell", "command": ["true"]},
            {
                "id": "loop",
                "type": "loop_group",
                "max_iterations": 2,
                "until_bash": ["true"],
                "depends_on": ["prep"],
                "nodes": [
                    {"id": "work", "type": "agent", "prompt": "Work"},
                    {"id": "ok", "type": "approval", "message": "OK?", "depends_on": ["work"]},
                ],
            },
        ],
    }
    catalog = ReadWorkflows(
        Hubs(("demo", "/hubs/demo")),
        lambda _: Files((WorkflowFile("workflows/demo/rounds.yaml", "rounds", rounds),)),
    ).list_workflows(Scope())

    assert catalog.problems == ()
    (item,) = catalog.items
    assert item.step_types == {"shell": 1, "loop_group": 1, "agent": 1, "approval": 1}
    assert [(step.id, step.max_iterations) for step in item.steps] == [("prep", None), ("loop", 2)]
    assert [step.id for step in item.steps[1].body] == ["work", "ok"]
    assert [(i.name, i.type, i.required, i.description) for i in item.inputs] == [
        ("issue", "string", True, "The issue"),
        ("tries", "integer", False, None),
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
