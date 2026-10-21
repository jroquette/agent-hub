"""An interactive scenario run's investigation: the pause at a divergence, the proposal, the
checks on an answer and what the answer does (P-5, P-6, P-8, AM-1, AM-3, AM-11;
docs/design/scenarios.md § Investigation, answers and workarounds).

**The pause.** In interactive mode ``HeldEnd`` holds back the engine's ``failed`` end when the
failed node is a top-level ``action`` or ``expect`` step and its kind is not ``config``: the
runner then records an ``investigation`` line (its ``gate``, ``<step>__investigation``, the
investigation's ``number`` and the divergence) and a ``gate`` line on that gate (attempt the
number, form ``choice``: ``pick``, ``retry``, ``stop``), and emits its ``gate.request``
(``human_gate``, reason ``investigation``). No end is recorded: the run is resumable, and the
resume runs the diverged step again as a new attempt. Past ``MAX_INVESTIGATIONS`` the end is not
held: the scenario run fails as in regression mode. A step in a ``loop_group`` body fails its
group, which is not an action step, so it is not investigated.

**The proposal** (``record_proposal``, for ``hub scenario propose``): findings get run-wide ids
(``f<n>``), options ``o<n>`` in the proposal; each option's steps are planned with origin
``agent`` (``workaround.plan_option``) and recorded with that plan; one ``finding`` event each.

**An answer** to an investigation gate is checked before it is recorded (``check_answer``): a
``pick`` names an option of the investigation's latest proposal that can be picked and whose
plan is still the one shown; anything else is refused and nothing is recorded.

**The resume** (``answer``): the gate is closed (a ``step_end`` on it) and ``stop`` ends the
scenario run ``cancelled`` (findings kept), ``retry`` goes on, and ``pick`` runs the option
first: ``workaround.start``, each step (origin ``agent``; the pick answered its ask) planned
again and run only while its plan is the one shown, ``workaround.end``. A failed workaround, or
one a crash cut (its start and no end: it is never run again silently), opens a new
investigation of the same step.
"""

import contextlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.action_command import deny_reason
from agent_hub.cli.action_runs import ActionExecutors, ActionLog, PinnedActions
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.run_log import now
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.cli.workflow_runs import (
    RecordedRun,
    WorkflowRunError,
    append_record,
)
from agent_hub.core.approvals.decide_gate import GateDecisionError, RequestedGate
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import PolicyDecision, find_environment
from agent_hub.core.scenarios.investigation import (
    CHOICES,
    INVESTIGATION_REASON,
    MAX_INVESTIGATIONS,
    PICK,
    STOP,
    Proposal,
    ProposedStep,
    investigation_gate,
    option_id,
)
from agent_hub.core.scenarios.policy_gates import INVESTIGATION, ask_gate, recorded_gate_kinds
from agent_hub.core.scenarios.run_record import (
    PROPOSAL,
    WORKAROUND_END,
    WORKAROUND_START,
    InvestigationView,
    OptionView,
    fold_records,
)
from agent_hub.core.scenarios.scenario_events import ScenarioEvents, WorkaroundFacts
from agent_hub.core.scenarios.workaround import (
    StepPlan,
    changed_step,
    needs_acceptance,
    pick_refusal,
    plan_option,
)
from agent_hub.core.workflows.failures import FailureKind, NodeFailedError, RetryRecord
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.nodes import ActionNode, ExpectNode
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import GateRequest, RunEnd, RunRecorder, StepEnd, StepStart
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions

LIMIT_REACHED: Final = "(investigation limit reached)"

type Record = dict[str, JsonValue]


def investigations(records: Sequence[Mapping[str, JsonValue]]) -> int:
    """How many investigations the scenario run opened."""
    return sum(1 for record in records if record.get("event") == INVESTIGATION)


def paused_line(run_id: str, scenario: str, step: str) -> str:
    return (
        f"run {run_id}: paused at {step} (investigation): open /scenarios/{scenario}/runs/"
        f"{run_id} in hub web (./hub web)"
    )


@dataclass(kw_only=True)
class HeldEnd:
    """The engine's ``RunRecorder`` of an interactive scenario run: everything goes to
    ``recorder``, except a ``failed`` end at an investigable step while investigations remain
    (``held``, then the runner opens the investigation)."""

    recorder: RunRecorder
    plan: WorkflowPlan
    opened: int
    held: RunEnd | None = None
    capped: bool = False
    # Each node's last failed attempt and its kind.
    failed: dict[str, tuple[int, FailureKind | None]] = field(default_factory=dict)

    def step_started(self, start: StepStart) -> None:
        self.recorder.step_started(start)

    def step_ended(self, end: StepEnd) -> None:
        if end.status == "failed":
            self.failed[end.node] = (end.attempt, end.failure_kind)
        self.recorder.step_ended(end)

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None:
        self.recorder.retry_scheduled(node, retry)

    def gate_requested(self, request: GateRequest) -> None:
        self.recorder.gate_requested(request)

    def run_ended(self, end: RunEnd) -> None:
        if end.status == "failed" and end.reason is not None and self._investigable(end.reason):
            if self.opened < MAX_INVESTIGATIONS:
                self.held = end
                return
            self.capped = True
        self.recorder.run_ended(end)

    def _investigable(self, node: str) -> bool:
        step = next((item for item in self.plan.document.nodes if item.id == node), None)
        kind = self.failed.get(node, (0, None))[1]
        return isinstance(step, ActionNode | ExpectNode) and kind not in (None, "config")


def open_investigation(
    folder: Path,
    recorded: RecordedRun,
    *,
    step: str,
    step_attempt: int,
    failure_kind: str | None,
    number: int,
) -> None:
    """Record investigation ``number`` of ``step`` and open its gate (a ``gate.request`` with
    reason ``investigation``)."""
    gate = investigation_gate(step)
    line: Record = {"event": INVESTIGATION, "step": step, "gate": gate, "number": number}
    line |= {"step_attempt": step_attempt, "failure_kind": failure_kind}
    append_record(folder, line, durable=True)
    message = (
        f"investigation {number}: step {step} diverged ({failure_kind or 'failed'}); answer"
        " pick <option id>, retry or stop"
    )
    recorded.gate_requested(
        GateRequest(
            gate,
            number,
            "approval",
            "choice",
            now(),
            CHOICES,
            message,
            reason=INVESTIGATION_REASON,
        )
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class Planned:
    """What an option is planned against: the hub's actions as read now and the effective
    environments, in the run's environment and pack."""

    hub: Path
    environment: str
    pack: str
    view: EffectiveEnvironments

    @classmethod
    def of(cls, hub: Path, header: Mapping[str, JsonValue]) -> Planned:
        effective = load_effective_config_or_exit(hub)
        return cls(
            hub=hub,
            environment=str(header.get("environment")),
            pack=str(header.get("pack")),
            view=effective_environments(effective.config, effective.local),
        )

    def option(
        self, steps: Sequence[ProposedStep], found: ActionDiscovery | None = None
    ) -> tuple[StepPlan, ...]:
        """The plan of ``steps`` (origin ``agent``) against ``found``, else the hub read now."""
        return plan_option(
            steps,
            entries=(found or discover_actions(self.hub)).actions,
            pack=self.pack,
            view=self.view,
            environment=self.environment,
        )

    def refusal(self, step: StepPlan) -> str:
        """Why ``step`` keeps its option from being picked, in plain words."""
        if step.problem is not None or step.effect is None or step.reason_kind is None:
            reason = step.problem or "cannot be planned"
        else:
            declared = find_environment(self.view, self.environment)
            decided = PolicyDecision(decision=step.decision, reason_kind=step.reason_kind)
            reason = deny_reason(
                decided,
                effect=step.effect,
                environment=self.environment,
                access=declared.access if declared is not None else None,
            ) or str(step.decision)
        return f"step {step.index} ({step.action}): {reason}"


def proposed_steps(option: OptionView) -> tuple[ProposedStep, ...]:
    """An option's steps as recorded, back as proposed steps."""
    steps: list[ProposedStep] = []
    for step in option.steps:
        given = step.get("with")
        inputs = given if isinstance(given, dict) else {}
        steps.append(ProposedStep(action=str(step.get("action")), inputs=inputs))
    return tuple(steps)


@dataclass(frozen=True, kw_only=True, slots=True)
class RecordedProposal:
    """A proposal as recorded: its number, the investigation's, and each option's plan."""

    proposal: int
    investigation: InvestigationView
    finding_ids: tuple[str, ...]
    plans: tuple[tuple[StepPlan, ...], ...]


def record_proposal(
    folder: Path,
    records: Sequence[Mapping[str, JsonValue]],
    proposal: Proposal,
    *,
    planned: Planned,
    events: ScenarioEvents,
    at: datetime,
) -> RecordedProposal:
    """Record ``proposal`` for the scenario run's open investigation, each option planned with
    origin ``agent``, and add one ``finding`` event per finding; ``WorkflowRunError`` when the
    run is not paused at an investigation."""
    view = fold_records(records)
    open_now = view.open_investigation
    if open_now is None:
        raise WorkflowRunError(f"the scenario run {folder.name} is not paused at an investigation")
    earlier = sum(
        len(found)
        for record in records
        if record.get("event") == PROPOSAL and isinstance(found := record.get("findings"), list)
    )
    number = 1 + sum(1 for record in records if record.get("event") == PROPOSAL)
    finding_ids = tuple(f"f{earlier + index}" for index in range(1, len(proposal.findings) + 1))
    plans = tuple(planned.option(option.steps) for option in proposal.options)
    findings: list[JsonValue] = [
        {"finding_id": ident, "title": item.title, "text": item.text, "evidence": item.evidence}
        for ident, item in zip(finding_ids, proposal.findings, strict=True)
    ]
    options: list[JsonValue] = [
        {
            "option_id": option_id(index),
            "summary": option.summary,
            "steps": [{"action": step.action, "with": dict(step.inputs)} for step in option.steps],
            "plan": [step.model_dump(mode="json") for step in plan],
        }
        for index, (option, plan) in enumerate(zip(proposal.options, plans, strict=True), 1)
    ]
    line: Record = {"event": PROPOSAL, "gate": open_now.gate, "number": open_now.number}
    line |= {"step": open_now.step, "proposal": number, "findings": findings, "options": options}
    append_record(folder, line, durable=True)
    for ident in finding_ids:
        events.finding_recorded(
            step=open_now.step, attempt=open_now.number, finding_id=ident, at=at
        )
    return RecordedProposal(
        proposal=number, investigation=open_now, finding_ids=finding_ids, plans=plans
    )


def option_lines(planned: Planned, recorded: RecordedProposal, proposal: Proposal) -> list[str]:
    """What ``hub scenario propose`` prints of each option: its plan, ``needs acceptance`` and
    why it cannot be picked."""
    lines: list[str] = []
    for index, (option, plan) in enumerate(zip(proposal.options, recorded.plans, strict=True), 1):
        accepted = "  (needs acceptance)" if needs_acceptance(plan) else ""
        lines.append(f"option {option_id(index)}: {option.summary}{accepted}")
        for step in plan:
            decision: str = step.decision
            if decision == "deny":
                decision = f"deny ({planned.refusal(step).partition(': ')[2]})"
            lines.append(f"  {step.index}  {step.action}  {step.effect or '-'}  {decision}")
        if (refused := pick_refusal(plan)) is not None:
            lines.append(f"  cannot be picked: {planned.refusal(refused)}")
    return lines


def check_answer(
    hub: Path,
    records: Sequence[Mapping[str, JsonValue]],
    *,
    gate: RequestedGate,
    answer: GateAnswer,
) -> None:
    """Refuse (``GateDecisionError``) an answer to an investigation gate that cannot stand: a
    ``pick`` of no option of its latest proposal, of an option that cannot be picked, or of one
    whose plan changed since it was shown. Any other gate passes untouched."""
    if recorded_gate_kinds(records).get(gate.node) != "investigation" or answer.choice != PICK:
        return
    view = fold_records(records)
    found = next(
        (
            item
            for item in view.investigations
            if (item.gate, item.number) == (gate.node, gate.attempt)
        ),
        None,
    )
    proposal = None if found is None else found.proposal
    if proposal is None:
        raise GateDecisionError("no option was proposed yet: retry, stop, or wait for a proposal")
    option = proposal.option((answer.text or "").strip())
    if option is None:
        known = ", ".join(item.option_id for item in proposal.options) or "none"
        raise GateDecisionError(f"pick names an option as its text: one of {known}")
    planned = Planned.of(hub, records[0])
    now = planned.option(proposed_steps(option))
    if (refused := pick_refusal(now)) is not None:
        reason = planned.refusal(refused)
        raise GateDecisionError(f"option {option.option_id} cannot be picked: {reason}")
    if (changed := changed_step(option.plan, now)) is not None:
        raise GateDecisionError(
            f"option {option.option_id} cannot be picked: the plan of step {changed.index}"
            f" ({changed.action}) changed since it was shown; ask for a new proposal"
        )


@dataclass(frozen=True, kw_only=True)
class AnswerPorts:
    """What answering an investigation on resume uses: the run's folder and record, its
    recorder and action log, the workflow executors whose children an interrupt stops, and
    where its actions run."""

    hub: Path
    folder: Path
    header: Mapping[str, JsonValue]
    records: Sequence[Mapping[str, JsonValue]]
    recorded: RecordedRun
    log: ActionLog
    inner: WorkflowExecutors
    roots: tuple[str, ...]
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)


def answer(ports: AnswerPorts, investigation: InvestigationView) -> int | None:
    """Act on the answered ``investigation``: the exit code when the scenario run stops or
    pauses again here, ``None`` when its engine goes on."""
    choice = investigation.choice
    if choice == PICK:
        failed = _workaround(ports, investigation)
        _close(ports, investigation)
        if failed is not None:
            return _reopen(ports, investigation, failed)
        return None
    _close(ports, investigation)
    if choice == STOP:
        ports.recorded.run_ended(RunEnd("cancelled", now(), reason=investigation.gate))
        typer.echo(f"run {ports.folder.name}: cancelled")
        return 1
    return None


def _close(ports: AnswerPorts, investigation: InvestigationView) -> None:
    """End the investigation's gate: a ``step_end`` on it with the answer."""
    output: JsonValue = {"choice": investigation.choice, "text": investigation.text or ""}
    ports.recorded.step_ended(
        StepEnd(
            investigation.gate,
            investigation.number,
            "ok",
            now(),
            output=output,
        )
    )


def _reopen(ports: AnswerPorts, investigation: InvestigationView, failed: str) -> int:
    """A failed workaround opens a new investigation of the same step, or fails the scenario
    run past the limit; the exit code."""
    run_id, step = ports.folder.name, investigation.step
    opened = investigations(ports.records)
    typer.echo(f"step {step}: {failed}")
    if opened >= MAX_INVESTIGATIONS:
        ports.recorded.run_ended(RunEnd("failed", now(), reason=step))
        typer.echo(f"run {run_id}: failed")
        typer.echo(f"step {step}: {failed} {LIMIT_REACHED}")
        return 1
    open_investigation(
        ports.folder,
        ports.recorded,
        step=step,
        step_attempt=0,
        failure_kind="workaround",
        number=opened + 1,
    )
    typer.echo(paused_line(run_id, str(ports.header.get("scenario")), step))
    return 0


def _workaround(ports: AnswerPorts, investigation: InvestigationView) -> str | None:
    """Run the picked option as workaround ``w<number>``; why it failed, or ``None``."""
    workaround_id = f"w{investigation.number}"
    started = any(
        record.get("event") == WORKAROUND_START and record.get("workaround_id") == workaround_id
        for record in ports.records
    )
    proposal = investigation.proposal
    option = None if proposal is None else proposal.option((investigation.text or "").strip())
    facts = WorkaroundFacts(
        step=investigation.step,
        attempt=investigation.number,
        workaround_id=workaround_id,
        option=(investigation.text or "").strip(),
        steps=0 if option is None else len(option.steps),
    )
    events = ports.log.events
    if started:
        # It started and never ended: it may have run, and is never run again silently.
        _workaround_end(ports, facts, "interrupted")
        return f"workaround {workaround_id} was cut short and is not run again"
    if option is None:
        return f"workaround {workaround_id}: no option {facts.option} to run"
    line: Record = {"event": WORKAROUND_START, "workaround_id": workaround_id}
    line |= {"number": investigation.number, "gate": investigation.gate, "option": facts.option}
    line |= {"steps": facts.steps, "approver": investigation.approver}
    append_record(ports.folder, line, durable=True)
    with ports.log.lock:
        events.workaround_started(facts, at=now())
        ports.log.sink.flush(events)
    failed = _run_steps(ports, investigation, option, workaround_id=workaround_id)
    _workaround_end(ports, facts, "ok" if failed is None else "failed")
    return failed


def _workaround_end(ports: AnswerPorts, facts: WorkaroundFacts, status: str) -> None:
    line: Record = {"event": WORKAROUND_END, "workaround_id": facts.workaround_id}
    append_record(ports.folder, line | {"number": facts.attempt, "status": status})
    events = ports.log.events
    with ports.log.lock:
        events.workaround_ended(facts, status=status, at=now())
        ports.log.sink.flush(events)


def _run_steps(
    ports: AnswerPorts, investigation: InvestigationView, option: OptionView, *, workaround_id: str
) -> str | None:
    """Run the option's steps in order, each planned again first; why one failed, or None."""
    planned = Planned.of(ports.hub, ports.header)
    steps = proposed_steps(option)
    for index in range(1, len(steps) + 1):
        found = discover_actions(ports.hub)
        current = planned.option(steps, found)[index - 1]
        shown = option.plan[index - 1] if index <= len(option.plan) else {}
        if current.decision == "deny" or dict(shown) != current.model_dump(mode="json"):
            return (
                f"workaround {workaround_id} step {index} ({current.action}): its plan changed"
                " since it was shown"
            )
        entry = next(item for item in found.actions if item.ref == current.action)
        ident = f"{investigation.gate}.w{index}"
        runner = ActionExecutors(
            hub=ports.hub,
            environment=planned.environment,
            view=planned.view,
            roots=ports.roots,
            pack=planned.pack,
            pinned=PinnedActions(
                entries=(entry,), files={entry.document_path: found.files[entry.document_path]}
            ),
            # The pick answered the asks of its steps.
            asks=frozenset({ident}),
            approvers={ask_gate(ident): investigation.approver or "unknown"},
            log=ports.log,
            inner=ports.inner,
            environ=ports.environ,
            noun="workaround",
            origin="agent",
        )
        try:
            runner.run_call(
                ident, action=entry.ref, attempt=investigation.number, inputs=current.inputs
            )
        except NodeFailedError as error:
            return f"workaround {workaround_id} step {index} ({current.action}): {error.kind}"
        except BaseException:
            with contextlib.suppress(Exception):
                runner.stop_children()
            raise
    return None
