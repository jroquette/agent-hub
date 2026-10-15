"""Deciding a workflow gate from hub web: the gate shown, the answer checked, the run resumed
(AC-213.18)."""

import threading
from collections.abc import Iterable, Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.approvals.approval import Approval, ApprovalKind
from agent_hub.core.approvals.decide_gate import MAX_TEXT_BYTES
from agent_hub.core.readmodels.filters import RunFilter
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.runs.workflow_run import IssueRef, WorkflowRun
from agent_hub.core.testing.read_model_builders import a_run
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.gate_decisions import (
    DecideWorkflowGate,
    GateDecisionRequest,
    ResumeAfterDecisionError,
    WorkflowGates,
)
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.launch import (
    LaunchSpec,
    RunConflictError,
    RunGuard,
    RunInputError,
    RunLaunchError,
)
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow

REVIEW = {
    "version": 1,
    "name": "review",
    "revision": 1,
    "inputs": {"issue": {"type": "string"}},
    "nodes": [
        {"id": "build", "type": "shell", "command": ["make"]},
        {
            "id": "sign-off",
            "type": "approval",
            "message": "Ship it?",
            "depends_on": ["build"],
            "decisions": [
                {"id": "approve", "label": "Approve"},
                {"id": "request-changes", "label": "Request changes"},
                {"id": "reject", "label": "Reject"},
            ],
            "capture_response": True,
        },
        {"id": "plain", "type": "approval", "message": "Go?", "depends_on": ["sign-off"]},
        {"id": "note", "type": "wait", "attention": "Why?", "depends_on": ["plain"]},
        {
            "id": "pick",
            "type": "wait",
            "attention": "Which?",
            "options": [{"id": "fast", "label": "Fast"}, {"id": "safe", "label": "Safe"}],
            "depends_on": ["note"],
        },
        {"id": "nap", "type": "wait", "duration": "1h", "depends_on": ["pick"]},
        {
            "id": "rework",
            "type": "loop_group",
            "depends_on": ["nap"],
            "max_iterations": 3,
            "until_when": "$check.output.decision == 'approve'",
            "nodes": [{"id": "check", "type": "approval", "message": "Again?"}],
        },
    ],
}


class Plans:
    def __init__(self) -> None:
        self.plan = plan_workflow(parse_workflow(REVIEW))

    def workflow_plan(self, project: str, name: str) -> tuple[str, WorkflowPlan]:
        if (project, name) != ("demo", "review"):
            raise EntityNotFoundError(entity="workflow", entity_id=f"{project}/{name}")
        return "/hubs/demo", self.plan

    def project_hubs(self) -> Iterable[tuple[str, str]]:
        return [("demo", "/hubs/demo")]


class Reads:
    """The read model: approvals by id and runs."""

    def __init__(self, *runs: WorkflowRun, approvals: Iterable[Approval] = ()) -> None:
        self.runs = runs
        self.approvals = {approval.id: approval for approval in approvals}

    def get_approval(self, approval_id: str) -> Approval:
        if approval_id not in self.approvals:
            raise EntityNotFoundError(entity="approval", entity_id=approval_id)
        return self.approvals[approval_id]

    def get_run(self, run_id: str) -> WorkflowRun:
        found = next((run for run in self.runs if run.id == run_id), None)
        if found is None:
            raise EntityNotFoundError(entity="run", entity_id=run_id)
        return found

    def list_runs(self, run_filter: RunFilter) -> Page[WorkflowRun]:
        items = tuple(
            run for run in self.runs if run.issue is not None and run.issue.key == run_filter.issue
        )
        return Page(items=items, next_cursor=None, total_estimate=len(items))


class Launcher:
    def __init__(self, live: Mapping[str, str | None] | None = None) -> None:
        self.live = dict(live or {})
        self.calls: list[tuple[str, Any]] = []
        self.refuse: RunConflictError | None = None
        self.resume_error: RunLaunchError | None = None

    def decide(self, hub_path: str, run_id: str, *, gate_id: str, answer: GateAnswer) -> None:
        self.calls.append(("decide", (hub_path, run_id, gate_id, answer)))
        if self.refuse is not None:
            raise self.refuse

    def resume(self, hub_path: str, run_id: str, *, issue: str | None) -> None:
        self.calls.append(("resume", (hub_path, run_id, issue)))
        if self.resume_error is not None:
            raise self.resume_error

    def start(self, spec: LaunchSpec) -> None:
        raise AssertionError(spec)

    def abandon(self, hub_path: str, run_id: str) -> None:
        raise AssertionError(run_id)

    def cancel(self, hub_path: str, run_id: str) -> bool:
        raise AssertionError(run_id)

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]:
        return self.live


def a_gate(node: str = "sign-off", **overrides: Any) -> Approval:
    gate_id = f"run-9:{node}:1"
    fields: dict[str, Any] = {
        "id": gate_id,
        "project": "demo",
        "repo": None,
        "kind": ApprovalKind.HUMAN_GATE,
        "title": "Human gate needs approval",
        "status": "open",
        "decided": False,
        "gate_id": gate_id,
        "session_id": "run:run-9",
        "requested_by": None,
        "requested_at": "2026-10-15T10:00:00Z",
        "request_event_id": "00000000-0000-4000-8000-000000000001",
    }
    return Approval.model_validate(fields | overrides)


def engine_run(**overrides: Any) -> WorkflowRun:
    return a_run(id="run-9", workflow="review", content_hash="sha256:abc", **overrides)


def decide(
    reads: Reads, launcher: Launcher, approval_id: str = "run-9:sign-off:1", **body: Any
) -> Any:
    guard = RunGuard(reads, launcher)  # type: ignore[arg-type]
    use_case = DecideWorkflowGate(WorkflowGates(reads, Plans(), Plans()), guard)  # type: ignore[arg-type]
    return use_case(approval_id, GateDecisionRequest.model_validate(body))


def gate_of(reads: Reads, approval_id: str) -> Any:
    return WorkflowGates(reads, Plans(), Plans()).gate(approval_id)  # type: ignore[arg-type]


def test_shows_decisions_with_labels_and_optional_text_when_gate_captures_response() -> None:
    gate = gate_of(Reads(engine_run(), approvals=[a_gate()]), "run-9:sign-off:1")

    assert (gate.run_id, gate.project, gate.workflow, gate.node, gate.attempt) == (
        "run-9",
        "demo",
        "review",
        "sign-off",
        1,
    )
    assert gate.form == "decision"
    assert [(choice.id, choice.label) for choice in gate.choices] == [
        ("approve", "Approve"),
        ("request-changes", "Request changes"),
        ("reject", "Reject"),
    ]
    assert gate.text == "optional"


def test_shows_default_decisions_and_no_text_when_gate_declares_none() -> None:
    gate = gate_of(Reads(engine_run(), approvals=[a_gate("plain")]), "run-9:plain:1")

    assert [choice.id for choice in gate.choices] == ["approve", "reject"]
    assert gate.text == "off"


def test_shows_required_text_when_attention_wait_has_no_options() -> None:
    gate = gate_of(Reads(engine_run(), approvals=[a_gate("note")]), "run-9:note:1")

    assert (gate.form, gate.choices, gate.text) == ("text", (), "required")


def test_shows_options_with_optional_text_when_attention_wait_has_options() -> None:
    gate = gate_of(Reads(engine_run(), approvals=[a_gate("pick")]), "run-9:pick:1")

    assert gate.form == "choice"
    assert [choice.id for choice in gate.choices] == ["fast", "safe"]
    assert gate.text == "optional"


def test_finds_gate_when_it_sits_in_a_loop_group_body() -> None:
    approval = a_gate("rework__check")

    gate = gate_of(Reads(engine_run(), approvals=[approval]), "run-9:rework__check:1")

    assert gate.node == "rework__check"
    assert [choice.id for choice in gate.choices] == ["approve", "reject"]


@pytest.mark.parametrize(
    ("approval", "code"),
    [
        (a_gate(kind=ApprovalKind.GUARD_ASK), "not_workflow_gate"),
        (a_gate(session_id="claude-1"), "not_workflow_gate"),
        (a_gate(gate_id="run-9:sign-off"), "not_workflow_gate"),
        (a_gate(gate_id="run-8:sign-off:1", session_id="run:run-9"), "not_workflow_gate"),
        (a_gate(status="approved", decided=True), "decided"),
        (a_gate("missing"), "gate_not_in_workflow"),
        (a_gate("build"), "gate_not_in_workflow"),
        (a_gate("nap"), "gate_not_in_workflow"),
    ],
)
def test_refuses_gate_when_approval_is_no_open_person_gate_of_the_workflow(
    approval: Approval, code: str
) -> None:
    with pytest.raises(RunConflictError) as caught:
        gate_of(Reads(engine_run(), approvals=[approval]), approval.id)

    assert caught.value.code == code


def test_refuses_gate_when_run_is_no_engine_run() -> None:
    reads = Reads(a_run(id="run-9", workflow="review"), approvals=[a_gate()])

    with pytest.raises(RunConflictError) as caught:
        gate_of(reads, "run-9:sign-off:1")

    assert caught.value.code == "not_engine_run"


def test_raises_not_found_when_approval_is_unknown() -> None:
    with pytest.raises(EntityNotFoundError):
        gate_of(Reads(engine_run()), "run-9:sign-off:1")


def test_records_decision_then_resumes_with_issue_when_answer_fits() -> None:
    run = engine_run(issue=IssueRef(key="DEM-7"))
    launcher = Launcher()

    accepted = decide(Reads(run, approvals=[a_gate()]), launcher, decision="reject", text="no")

    assert launcher.calls == [
        ("decide", ("/hubs/demo", "run-9", "run-9:sign-off:1", GateAnswer("reject", "no"))),
        ("resume", ("/hubs/demo", "run-9", "DEM-7")),
    ]
    assert (accepted.approval_id, accepted.run_id, accepted.project) == (
        "run-9:sign-off:1",
        "run-9",
        "demo",
    )
    assert accepted.decision == "reject"


def test_records_text_answer_when_attention_wait_takes_text() -> None:
    launcher = Launcher()

    decide(Reads(engine_run(), approvals=[a_gate("note")]), launcher, "run-9:note:1", text="ok")

    assert launcher.calls[0][1][3] == GateAnswer(None, "ok")


@pytest.mark.parametrize(
    ("node", "body", "message"),
    [
        ("sign-off", {"decision": "merge"}, 'no decision "merge"'),
        ("sign-off", {}, "this gate needs a decision"),
        ("plain", {"decision": "approve", "text": "why"}, "this gate takes no text"),
        ("note", {"decision": "fast", "text": "x"}, "this wait takes no option"),
        ("note", {"text": "  "}, "this wait needs a text answer"),
        ("pick", {"decision": "slow"}, 'no option "slow"'),
    ],
)
def test_refuses_answer_without_launching_when_it_does_not_fit_gate(
    node: str, body: dict[str, Any], message: str
) -> None:
    launcher = Launcher()

    with pytest.raises(RunInputError, match=message):
        decide(Reads(engine_run(), approvals=[a_gate(node)]), launcher, f"run-9:{node}:1", **body)

    assert launcher.calls == []


def test_refuses_text_without_launching_when_it_is_longer_than_the_cap() -> None:
    launcher = Launcher()
    text = "é" * (MAX_TEXT_BYTES // 2 + 1)

    with pytest.raises(RunInputError, match=f"longer than {MAX_TEXT_BYTES} bytes"):
        decide(Reads(engine_run(), approvals=[a_gate()]), launcher, decision="approve", text=text)

    assert launcher.calls == []


def test_refuses_decision_when_run_child_still_runs() -> None:
    launcher = Launcher(live={"run-9": None})

    with pytest.raises(RunConflictError) as caught:
        decide(Reads(engine_run(), approvals=[a_gate()]), launcher, decision="approve")

    assert caught.value.code == "in_use"
    assert launcher.calls == []


def test_refuses_decision_when_issue_has_another_live_run() -> None:
    run = engine_run(issue=IssueRef(key="DEM-7"))
    launcher = Launcher(live={"run-3": "DEM-7"})

    with pytest.raises(RunConflictError) as caught:
        decide(Reads(run, approvals=[a_gate()]), launcher, decision="approve")

    assert (caught.value.code, caught.value.run_id) == ("live_run", "run-3")
    assert launcher.calls == []


def test_refuses_decision_when_run_already_ended() -> None:
    launcher = Launcher()

    with pytest.raises(RunConflictError) as caught:
        decide(Reads(engine_run(status="done"), approvals=[a_gate()]), launcher, decision="approve")

    assert caught.value.code == "ended"
    assert launcher.calls == []


def test_does_not_resume_when_record_refuses_decision() -> None:
    launcher = Launcher()
    launcher.refuse = RunConflictError(code="refused", reason="no", run_id="run-9")

    with pytest.raises(RunConflictError):
        decide(Reads(engine_run(), approvals=[a_gate()]), launcher, decision="approve")

    assert [call for call, _ in launcher.calls] == ["decide"]


def test_reports_decision_kept_when_resume_cannot_start() -> None:
    launcher = Launcher()
    launcher.resume_error = RunLaunchError("spawn failed")

    with pytest.raises(ResumeAfterDecisionError, match="decision is recorded") as caught:
        decide(Reads(engine_run(), approvals=[a_gate()]), launcher, decision="approve")

    assert isinstance(caught.value, RunLaunchError)
    assert [call for call, _ in launcher.calls] == ["decide", "resume"]


def test_holds_run_lock_from_live_check_through_resume_when_deciding() -> None:
    reads = Reads(engine_run(), approvals=[a_gate()])
    launcher = Launcher()
    guard = RunGuard(reads, launcher)  # type: ignore[arg-type]
    held: list[bool] = []
    launcher.decide = lambda *_, **__: held.append(guard.lock.locked())  # type: ignore[method-assign]
    launcher.resume = lambda *_, **__: held.append(guard.lock.locked())  # type: ignore[method-assign]
    use_case = DecideWorkflowGate(WorkflowGates(reads, Plans(), Plans()), guard)  # type: ignore[arg-type]

    use_case("run-9:sign-off:1", GateDecisionRequest(decision="approve"))

    assert held == [True, True]
    assert not guard.lock.locked()


def test_one_decision_launches_when_two_arrive_together() -> None:
    reads = Reads(engine_run(), approvals=[a_gate()])
    launcher = Launcher()
    guard = RunGuard(reads, launcher)  # type: ignore[arg-type]
    use_case = DecideWorkflowGate(WorkflowGates(reads, Plans(), Plans()), guard)  # type: ignore[arg-type]
    entered, release = threading.Event(), threading.Event()
    original_decide, original_resume = launcher.decide, launcher.resume

    def slow_decide(hub_path: str, run_id: str, **answer: Any) -> None:
        # The first decision waits between the live check and its resume.
        original_decide(hub_path, run_id, **answer)
        entered.set()
        release.wait(5)

    def resume(hub_path: str, run_id: str, *, issue: str | None) -> None:
        original_resume(hub_path, run_id, issue=issue)
        launcher.live[run_id] = issue

    launcher.decide = slow_decide  # type: ignore[method-assign]
    launcher.resume = resume  # type: ignore[method-assign]
    errors: list[RunConflictError] = []

    def call() -> None:
        try:
            use_case("run-9:sign-off:1", GateDecisionRequest(decision="approve"))
        except RunConflictError as error:
            errors.append(error)

    first = threading.Thread(target=call)
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=call)
    second.start()
    second.join(0.3)
    release.set()
    first.join(5)
    second.join(5)

    assert [name for name, _ in launcher.calls] == ["decide", "resume"]
    assert [error.code for error in errors] == ["in_use"]


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "Approve"},
        {"decision": "a" * 65},
        {"text": "a\x00b"},
        {"text": "a\ud800b"},
        {"decision": "approve", "extra": 1},
        {"decision": 1},
    ],
)
def test_refuses_body_when_it_breaks_the_request_shape(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        GateDecisionRequest.model_validate(body)
