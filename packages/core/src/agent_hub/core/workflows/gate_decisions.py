"""Decide a workflow gate from hub web (AC-213.18, ADR 0032): the gate, its answer, the resume.

``WorkflowGates.gate`` shows what answers an open ``human_gate`` approval of an engine run: its
run, node and attempt (from the approval's ``gate_id``, ``<run>:<node>:<attempt>``, in the run's
session ``run:<run>``), its form (``decision``, ``choice`` or ``text``), the choices with their
labels and whether it takes a text, read from the workflow's current definition (the run graph
does the same, AGH-226). ``DecideWorkflowGate`` checks the answer against that gate (422), then,
under the run commands' lock (``RunGuard``), refuses a run that ended, whose child still runs or
whose issue has another live run (409), has the launcher record the decision (``hub workflow
decide``: the CLI's ``DecideGate`` over the run's record, where ``web``) and resumes the run
detached. A record that refuses the decision (the gate closed or was decided meanwhile) answers
409 and nothing resumes; a resume that cannot start leaves the decision recorded (502), and the
run can be resumed later.
"""

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.approvals.decide_gate import MAX_TEXT_BYTES
from agent_hub.core.readmodels.read_ports import EventReadModels
from agent_hub.core.workflows.events import issue_key
from agent_hub.core.workflows.gates import GateAnswer, GateForm, answer_problem, gate_form
from agent_hub.core.workflows.launch import (
    RUN_ID_PATTERN,
    RunConflictError,
    RunGuard,
    RunInputError,
    RunLaunchError,
    WorkflowPlans,
    engine_run_target,
    refuse_busy,
)
from agent_hub.core.workflows.nodes import ApprovalNode, WaitNode
from agent_hub.core.workflows.workflow_reads import ProjectHubs

RUN_SESSION_PREFIX: Final = "run:"
MAX_CHOICE_CHARS: Final = 64

type TextUse = Literal["off", "optional", "required"]


class GateChoice(BaseModel):
    """A decision or option a person may pick, with its label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str


class WorkflowGate(BaseModel):
    """An open gate a person answers: where it is and what answers it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str
    run_id: str
    project: str
    workflow: str
    node: str
    attempt: int
    # ``decision``, ``choice`` or ``text``: a timed wait is no gate a person answers.
    form: GateForm
    choices: tuple[GateChoice, ...]
    text: TextUse


class GateDecisionRequest(BaseModel):
    """The body of ``POST /approvals/{id}/decision``: a decision or option id and/or a text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: (
        Annotated[
            str,
            StringConstraints(
                strict=True, max_length=MAX_CHOICE_CHARS, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$"
            ),
        ]
        | None
    ) = None
    text: Annotated[str, StringConstraints(strict=True, pattern=r"^[^\x00]*$")] | None = None


class GateDecided(BaseModel):
    """What a decision did: the gate's approval, its run and project, and the answer's id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str
    run_id: str
    project: str
    decision: str | None


class ResumeAfterDecisionError(RunLaunchError):
    """The decision is recorded, but the run's resume could not start (answers 502)."""


class WorkflowGates:
    """The open person gates of engine runs, as hub web shows them."""

    def __init__(self, runs: EventReadModels, hubs: ProjectHubs, plans: WorkflowPlans) -> None:
        self._runs, self._hubs, self._plans = runs, hubs, plans

    def gate(self, approval_id: str) -> WorkflowGate:
        """The open gate ``approval_id`` names; ``RunConflictError`` when it is no open gate a
        person answers in an engine run's workflow, ``EntityNotFoundError`` when unknown."""
        return self.target(approval_id)[0]

    def target(self, approval_id: str) -> tuple[WorkflowGate, str]:
        """The gate and its run's hub folder."""
        approval = self._runs.get_approval(approval_id)
        parts = approval.gate_id.split(":")
        if (
            approval.kind != ApprovalKind.HUMAN_GATE
            or len(parts) != 3  # noqa: PLR2004 -- <run>:<node>:<attempt>
            or approval.session_id != f"{RUN_SESSION_PREFIX}{parts[0]}"
            or not RUN_ID_PATTERN.fullmatch(parts[0])
            or not parts[2].isdecimal()
        ):
            reason = "the approval is not a gate of a workflow run"
            raise RunConflictError(code="not_workflow_gate", reason=reason)
        run_id, node_id, attempt = parts[0], parts[1], int(parts[2])
        if approval.decided:
            reason = f"the gate is already decided ({approval.status})"
            raise RunConflictError(code="decided", reason=reason, run_id=run_id)
        run, hub_path = engine_run_target(self._runs, self._hubs, run_id)
        _, plan = self._plans.workflow_plan(run.project, run.workflow)
        node = next((found for found in plan.all_nodes() if found.id == node_id), None)
        if not isinstance(node, ApprovalNode | WaitNode) or gate_form(node) == "timer":
            reason = f"the workflow {run.workflow} has no gate a person answers at {node_id}"
            raise RunConflictError(code="gate_not_in_workflow", reason=reason, run_id=run_id)
        form = gate_form(node)
        gate = WorkflowGate(
            approval_id=approval.id,
            run_id=run_id,
            project=run.project,
            workflow=run.workflow,
            node=node_id,
            attempt=attempt,
            form=form,
            choices=_choices(node),
            text=_text_use(node, form),
        )
        return gate, hub_path


class DecideWorkflowGate:
    """``POST /approvals/{id}/decision``: record a person's answer, then resume the run."""

    def __init__(self, gates: WorkflowGates, guard: RunGuard) -> None:
        self._gates, self._guard = gates, guard

    def __call__(self, approval_id: str, request: GateDecisionRequest) -> GateDecided:
        gate, hub_path = self._gates.target(approval_id)
        answer = GateAnswer(request.decision, request.text)
        _check_answer(gate, answer)
        runs, launcher = self._guard.runs, self._guard.launcher
        with self._guard.lock:
            run = runs.get_run(gate.run_id)
            refuse_busy(run, hub_path, launcher)
            issue = None if run.issue is None else issue_key(run.issue.key)
            if issue is not None:
                self._guard.refuse_live(run.project, hub_path, issue, besides=run.id)
            launcher.decide(hub_path, run.id, gate_id=approval_id, answer=answer)
            try:
                launcher.resume(hub_path, run.id, issue=issue)
            except RunLaunchError as error:
                message = f"the decision is recorded, but the run did not resume: {error}"
                raise ResumeAfterDecisionError(message) from None
        return GateDecided(
            approval_id=approval_id,
            run_id=run.id,
            project=run.project,
            decision=request.decision,
        )


def _choices(node: ApprovalNode | WaitNode) -> tuple[GateChoice, ...]:
    declared = node.decisions if isinstance(node, ApprovalNode) else node.options or ()
    return tuple(GateChoice(id=choice.id, label=choice.label) for choice in declared)


def _text_use(node: ApprovalNode | WaitNode, form: GateForm) -> TextUse:
    if form == "text":
        return "required"
    if isinstance(node, ApprovalNode) and not node.capture_response:
        return "off"
    return "optional"


def _check_answer(gate: WorkflowGate, answer: GateAnswer) -> None:
    """``RunInputError`` when ``answer`` cannot answer ``gate``."""
    choices = tuple(choice.id for choice in gate.choices)
    if (problem := answer_problem(gate.form, choices, answer)) is not None:
        raise RunInputError(problem)
    if gate.text == "off" and answer.text is not None:
        raise RunInputError("this gate takes no text")
    if len((answer.text or "").encode()) > MAX_TEXT_BYTES:
        raise RunInputError(f"the text is longer than {MAX_TEXT_BYTES} bytes")
