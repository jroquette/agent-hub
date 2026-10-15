from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.readmodels.filters import ApprovalFilter
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.read_model_builders import a_run, an_approval
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.gate_decisions import DecideWorkflowGate, WorkflowGates
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.launch import (
    DecisionUnknownError,
    LaunchSpec,
    RunConflictError,
    RunGuard,
    RunLaunchError,
)
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow


def test_maps_filters_when_approvals_listed(wired: Any) -> None:
    wired.events.approvals.append(an_approval())

    response = wired.client.get(
        "/api/v1/approvals", params={"kind": "guard_ask", "status": "all", "limit": "10"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"] == [an_approval().model_dump(mode="json")]
    assert wired.events.calls == [
        ("list_approvals", ApprovalFilter(kind=ApprovalKind.GUARD_ASK, status="all", limit=10))
    ]


def test_maps_approval_when_approval_requested(wired: Any) -> None:
    wired.events.approvals.append(an_approval())

    response = wired.client.get("/api/v1/approvals/toolu_demo_1")

    assert response.json()["how_to_decide"] == an_approval().how_to_decide


def test_answers_not_found_when_approval_unknown(wired: Any) -> None:
    assert wired.client.get("/api/v1/approvals/nope").status_code == 404


# Workflow gates decided from hub web (AC-213.18): a strict write, then the run resumes.
OWN = {"Origin": "http://127.0.0.1:7420"}
SHIP = {
    "version": 1,
    "name": "ship",
    "revision": 1,
    "nodes": [
        {
            "id": "ok",
            "type": "approval",
            "message": "Ship?",
            "capture_response": True,
            "decisions": [
                {"id": "approve", "label": "Approve"},
                {"id": "request-changes", "label": "Request changes"},
                {"id": "reject", "label": "Reject"},
            ],
        }
    ],
}
GATE_ID = "run-9:ok:1"


class Plans:
    def workflow_plan(self, project: str, name: str) -> tuple[str, WorkflowPlan]:
        if (project, name) != ("demo", "ship"):
            raise EntityNotFoundError(entity="workflow", entity_id=f"{project}/{name}")
        return "/hubs/demo", plan_workflow(parse_workflow(SHIP))

    def project_hubs(self) -> Iterable[tuple[str, str]]:
        return [("demo", "/hubs/demo")]


class Launcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.refuse = False
        self.resume_error = False
        self.decide_error: Exception | None = None

    def decide(self, hub_path: str, run_id: str, *, gate_id: str, answer: GateAnswer) -> None:
        self.calls.append(("decide", (run_id, gate_id, answer)))
        if self.refuse:
            raise RunConflictError(code="refused", reason="refused", run_id=run_id)
        if self.decide_error is not None:
            raise self.decide_error

    def resume(self, hub_path: str, run_id: str, *, issue: str | None) -> None:
        self.calls.append(("resume", run_id))
        if self.resume_error:
            raise RunLaunchError("spawn")

    def start(self, spec: LaunchSpec) -> None:
        raise AssertionError(spec)

    def abandon(self, hub_path: str, run_id: str) -> None:
        raise AssertionError(run_id)

    def cancel(self, hub_path: str, run_id: str) -> bool:
        raise AssertionError(run_id)

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]:
        return {}


@pytest.fixture
def gates(wired: Any) -> Any:
    launcher = Launcher()
    plans = Plans()
    gates = WorkflowGates(wired.events, plans, plans)
    wired.wire(
        workflow_gates=gates,
        gate_decisions=DecideWorkflowGate(gates, RunGuard(wired.events, launcher)),
    )
    wired.events.runs.append(a_run(id="run-9", workflow="ship", content_hash="sha256:abc"))
    wired.events.approvals.append(
        an_approval(
            id=GATE_ID,
            gate_id=GATE_ID,
            kind=ApprovalKind.HUMAN_GATE,
            session_id="run:run-9",
            path=None,
            rule=None,
        )
    )
    wired.launcher = launcher
    return wired


def test_shows_choices_and_text_use_when_gate_of_open_approval_requested(gates: Any) -> None:
    response = gates.client.get(f"/api/v1/approvals/{GATE_ID}/gate")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["run_id"], body["node"], body["form"], body["text"]) == (
        "run-9",
        "ok",
        "decision",
        "optional",
    )
    assert [choice["label"] for choice in body["choices"]] == [
        "Approve",
        "Request changes",
        "Reject",
    ]


def test_answers_conflict_when_gate_of_guard_ask_requested(gates: Any) -> None:
    gates.events.approvals.append(an_approval())

    response = gates.client.get("/api/v1/approvals/toolu_demo_1/gate")

    assert response.status_code == 409
    assert response.json()["code"] == "not_workflow_gate"


def test_records_decision_and_resumes_when_owned_decision_posted(gates: Any) -> None:
    body = {"decision": "request-changes", "text": "add tests"}

    response = gates.client.post(f"/api/v1/approvals/{GATE_ID}/decision", json=body, headers=OWN)

    assert response.status_code == 202, response.text
    assert response.json() == {
        "approval_id": GATE_ID,
        "run_id": "run-9",
        "project": "demo",
        "decision": "request-changes",
    }
    assert response.headers["Location"] == f"/api/v1/approvals/{GATE_ID}"
    assert gates.launcher.calls == [
        ("decide", ("run-9", GATE_ID, GateAnswer("request-changes", "add tests"))),
        ("resume", "run-9"),
    ]


def test_answers_unprocessable_without_launch_when_decision_is_not_declared(gates: Any) -> None:
    body = {"decision": "merge"}

    response = gates.client.post(f"/api/v1/approvals/{GATE_ID}/decision", json=body, headers=OWN)

    assert response.status_code == 422
    assert 'no decision "merge"' in response.json()["detail"]
    assert gates.launcher.calls == []


def test_answers_unprocessable_when_body_has_unknown_key(gates: Any) -> None:
    body = {"decision": "approve", "approver": "someone"}

    response = gates.client.post(f"/api/v1/approvals/{GATE_ID}/decision", json=body, headers=OWN)

    assert response.status_code == 422
    assert gates.launcher.calls == []


def test_answers_conflict_without_resume_when_record_refuses_decision(gates: Any) -> None:
    gates.launcher.refuse = True

    response = gates.client.post(
        f"/api/v1/approvals/{GATE_ID}/decision", json={"decision": "approve"}, headers=OWN
    )

    assert response.status_code == 409
    assert response.json()["code"] == "refused"
    assert [call for call, _ in gates.launcher.calls] == ["decide"]


def test_answers_bad_gateway_saying_decision_kept_when_resume_cannot_start(gates: Any) -> None:
    gates.launcher.resume_error = True

    response = gates.client.post(
        f"/api/v1/approvals/{GATE_ID}/decision", json={"decision": "approve"}, headers=OWN
    )

    assert response.status_code == 502
    problem = response.json()
    assert problem["type"] == "urn:agent-hub:problem:workflow-run-resume-failed"
    assert "decision is recorded" in problem["detail"]
    assert [call for call, _ in gates.launcher.calls] == ["decide", "resume"]


def test_answers_bad_gateway_saying_decision_unknown_when_decide_times_out(gates: Any) -> None:
    gates.launcher.decide_error = DecisionUnknownError("timed out")

    response = gates.client.post(
        f"/api/v1/approvals/{GATE_ID}/decision", json={"decision": "approve"}, headers=OWN
    )

    assert response.status_code == 502
    problem = response.json()
    assert problem["type"] == "urn:agent-hub:problem:workflow-run-decision-unknown"
    assert "may be recorded" in problem["detail"]
    assert "nothing was changed" not in problem["detail"].lower()
    assert [call for call, _ in gates.launcher.calls] == ["decide"]


def test_answers_conflict_when_approval_already_decided(gates: Any) -> None:
    gates.events.approvals[-1] = gates.events.approvals[-1].model_copy(
        update={"status": "approved", "decided": True}
    )

    response = gates.client.post(
        f"/api/v1/approvals/{GATE_ID}/decision", json={"decision": "approve"}, headers=OWN
    )

    assert response.status_code == 409
    assert response.json()["code"] == "decided"
    assert gates.launcher.calls == []


def test_refuses_decision_when_origin_is_another_site(gates: Any) -> None:
    response = gates.client.post(
        f"/api/v1/approvals/{GATE_ID}/decision",
        json={"decision": "approve"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert gates.launcher.calls == []


def test_answers_not_implemented_when_decisions_not_wired(wired: Any) -> None:
    response = wired.client.post(
        f"/api/v1/approvals/{GATE_ID}/decision", json={"decision": "approve"}, headers=OWN
    )

    assert response.status_code == 501
