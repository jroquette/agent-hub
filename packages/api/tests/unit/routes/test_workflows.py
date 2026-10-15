from collections.abc import Iterable
from typing import Any

import pytest

from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile
from agent_hub.core.workflows.workflow_reads import ReadWorkflows

SHIP = {
    "version": 1,
    "name": "ship",
    "revision": 1,
    "nodes": [
        {"id": "build", "type": "shell", "command": ["make"]},
        {"id": "review", "type": "agent", "prompt": "Review it", "depends_on": ["build"]},
    ],
}


class Hubs:
    def project_hubs(self) -> Iterable[tuple[str, str]]:
        return [("demo", "/hubs/demo")]


class Files:
    def fingerprint(self) -> object:
        return 1

    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        return [
            WorkflowFile("<builtin>/base/ship.yaml", "ship", SHIP, origin="builtin"),
            LoadProblem("workflows/mine/bad.yaml", 3, "$", "duplicate key 'name'"),
        ]


@pytest.fixture
def reads(wired: Any) -> Any:
    wired.wire(workflow_reads=ReadWorkflows(Hubs(), lambda _hub: Files()))
    return wired


def test_lists_workflows_and_problems_when_hubs_have_workflows(reads: Any) -> None:
    response = reads.client.get("/api/v1/workflows", params={"project": "demo"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [(item["name"], item["source"], item["layer_count"]) for item in body["items"]] == [
        ("ship", "builtin", 2)
    ]
    assert body["problems"] == [
        {
            "project": "demo",
            "file": "workflows/mine/bad.yaml",
            "line": 3,
            "key": "$",
            "message": "duplicate key 'name'",
        }
    ]


def test_gives_document_and_layers_when_workflow_requested(reads: Any) -> None:
    response = reads.client.get("/api/v1/workflows/demo/ship")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document"] == SHIP
    assert body["layers"] == [
        [{"id": "build", "type": "shell", "depends_on": [], "description": None}],
        [{"id": "review", "type": "agent", "depends_on": ["build"], "description": None}],
    ]


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("/api/v1/workflows/demo/bad", "No workflow with id 'demo/bad'."),
        ("/api/v1/workflows/nope/ship", "No project with id 'nope'."),
    ],
)
def test_answers_not_found_when_workflow_or_project_unknown(
    reads: Any, path: str, detail: str
) -> None:
    response = reads.client.get(path)

    assert response.status_code == 404
    assert response.json()["detail"] == detail


def test_answers_not_implemented_when_workflow_reads_not_wired(wired: Any) -> None:
    response = wired.client.get("/api/v1/workflows")

    assert response.status_code == 501


class RecordingReads:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_workflows(self, scope: Any) -> Any:
        self.calls.append("list")
        raise AssertionError(scope)

    def get_workflow(self, project: str, name: str) -> Any:
        self.calls.append("get")
        raise AssertionError((project, name))


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/workflows/{'p' * 201}/ship",
        f"/api/v1/workflows/demo/{'n' * 201}",
        f"/api/v1/workflows?project={'p' * 201}",
    ],
)
def test_refuses_parameter_when_over_200_characters(wired: Any, path: str) -> None:
    recording = RecordingReads()
    wired.wire(workflow_reads=recording)

    response = wired.client.get(path)

    assert response.status_code == 400
    assert recording.calls == []
