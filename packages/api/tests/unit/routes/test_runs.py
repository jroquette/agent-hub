from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from agent_hub.core.readmodels.filters import RunFilter
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.testing.read_model_builders import a_run
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.launch import (
    ControlWorkflowRun,
    LaunchSpec,
    RunLaunchError,
    StartWorkflowRun,
)
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow


def test_maps_filters_when_runs_listed(wired: Any) -> None:
    wired.events.runs.append(a_run())

    response = wired.client.get(
        "/api/v1/workflow-runs",
        params={"project": "demo", "stage": "IMPLEMENTING", "mode": "live", "issue": "DEM-7"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == "1a2b3c4d"
    assert wired.events.calls == [
        (
            "list_runs",
            RunFilter(project="demo", stage=Stage.IMPLEMENTING, mode="live", issue="DEM-7"),
        )
    ]


def test_maps_workflow_and_failure_kind_when_runs_filtered_by_them(wired: Any) -> None:
    response = wired.client.get(
        "/api/v1/workflow-runs", params={"workflow": "ship", "failure_kind": "timeout"}
    )

    assert response.status_code == 200, response.text
    assert wired.events.calls == [("list_runs", RunFilter(workflow="ship", failure_kind="timeout"))]


def test_refuses_failure_kind_when_kind_unknown(wired: Any) -> None:
    response = wired.client.get("/api/v1/workflow-runs", params={"failure_kind": "boom"})

    assert response.status_code == 400
    assert wired.events.calls == []


def test_maps_run_when_run_requested(wired: Any) -> None:
    wired.events.runs.append(a_run())

    response = wired.client.get("/api/v1/workflow-runs/1a2b3c4d")

    assert response.json() == a_run().model_dump(mode="json")


def test_answers_not_found_when_run_unknown(wired: Any) -> None:
    response = wired.client.get("/api/v1/workflow-runs/ffffffff")

    assert response.status_code == 404
    assert response.json()["detail"] == "No run with id 'ffffffff'."


# The run commands (AC-213.19): strict writes, so the server's own Origin and a JSON body.
OWN = {"Origin": "http://127.0.0.1:7420"}
FIX = {
    "version": 1,
    "name": "fix",
    "revision": 1,
    "inputs": {"issue": {"type": "string", "required": True}},
    "nodes": [{"id": "work", "type": "shell", "command": ["make"]}],
}


class Plans:
    def workflow_plan(self, project: str, name: str) -> tuple[str, WorkflowPlan]:
        if (project, name) != ("demo", "fix"):
            raise EntityNotFoundError(entity="workflow", entity_id=f"{project}/{name}")
        return "/hubs/demo", plan_workflow(parse_workflow(FIX))

    def project_hubs(self) -> Iterable[tuple[str, str]]:
        return [("demo", "/hubs/demo")]


class Launcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None

    def _call(self, name: str, value: object) -> None:
        self.calls.append((name, value))
        if self.error is not None:
            raise self.error

    def start(self, spec: LaunchSpec) -> None:
        self._call("start", spec.inputs)

    def resume(self, hub_path: str, run_id: str) -> None:
        self._call("resume", run_id)

    def abandon(self, hub_path: str, run_id: str) -> None:
        self._call("abandon", run_id)

    def cancel(self, hub_path: str, run_id: str) -> bool:
        self._call("cancel", run_id)
        return True

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]:
        return {}


@pytest.fixture
def commands(wired: Any) -> Any:
    launcher = Launcher()
    plans = Plans()
    wired.wire(
        run_starts=StartWorkflowRun(plans, wired.events, launcher, mint=lambda: "run-1"),
        run_control=ControlWorkflowRun(plans, wired.events, launcher),
    )
    wired.launcher = launcher
    return wired


def test_starts_run_with_location_when_body_fits(commands: Any) -> None:
    body = {"project": "demo", "workflow": "fix", "inputs": {"issue": "DEM-7"}, "live": True}

    response = commands.client.post("/api/v1/workflow-runs", json=body, headers=OWN)

    assert response.status_code == 202, response.text
    assert response.json() == {"run_id": "run-1", "project": "demo", "action": "start"}
    assert response.headers["Location"] == "/api/v1/workflow-runs/run-1"
    assert commands.launcher.calls == [("start", {"issue": "DEM-7"})]


@pytest.mark.parametrize(
    ("body", "status", "kind"),
    [
        ({"project": "demo", "workflow": "fix"}, 422, "invalid-inputs"),
        ({"project": "demo", "workflow": "fix", "extra": 1}, 422, None),
        ({"project": "demo", "workflow": "issue-to-pr"}, 409, "tracker-workflow"),
        ({"project": "demo", "workflow": "nope"}, 404, None),
    ],
)
def test_answers_problem_when_start_refused(
    commands: Any, *, body: dict[str, Any], status: int, kind: str | None
) -> None:
    response = commands.client.post("/api/v1/workflow-runs", json=body, headers=OWN)

    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    if kind is not None:
        assert response.json()["type"] == f"urn:agent-hub:problem:workflow-run-{kind}"
    assert commands.launcher.calls == []


def test_answers_bad_gateway_when_child_cannot_start(commands: Any) -> None:
    commands.launcher.error = RunLaunchError("cannot start: /home/demo/secret path")
    body = {"project": "demo", "workflow": "fix", "inputs": {"issue": "DEM-7"}}

    response = commands.client.post("/api/v1/workflow-runs", json=body, headers=OWN)

    assert response.status_code == 502
    assert "/home/demo" not in response.text


@pytest.mark.parametrize(("action", "status"), [("cancel", 202), ("resume", 202), ("abandon", 200)])
def test_runs_command_when_engine_run_idle(commands: Any, action: str, status: int) -> None:
    commands.events.runs.append(a_run(id="run-9", content_hash="sha256:abc", status="failed"))

    response = commands.client.post(f"/api/v1/workflow-runs/run-9/{action}", json={}, headers=OWN)

    assert response.status_code == status, response.text
    assert response.json()["action"] == action
    assert commands.launcher.calls == [(action, "run-9")]


def test_answers_conflict_with_run_id_when_run_already_ended(commands: Any) -> None:
    commands.events.runs.append(a_run(id="run-9", content_hash="sha256:abc", status="done"))

    response = commands.client.post("/api/v1/workflow-runs/run-9/resume", json={}, headers=OWN)

    assert response.status_code == 409
    assert (response.json()["code"], response.json()["run_id"]) == ("ended", "run-9")


@pytest.mark.parametrize("run_id", ["Run-9", "-x", "a" * 33])
def test_refuses_run_id_when_not_cli_pattern(commands: Any, run_id: str) -> None:
    response = commands.client.post(f"/api/v1/workflow-runs/{run_id}/cancel", json={}, headers=OWN)

    assert response.status_code == 400
    assert commands.launcher.calls == []


def test_answers_not_implemented_when_commands_not_wired(wired: Any) -> None:
    response = wired.client.post("/api/v1/workflow-runs/run-9/abandon", json={}, headers=OWN)

    assert response.status_code == 501
