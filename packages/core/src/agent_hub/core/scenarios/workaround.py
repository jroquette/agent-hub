"""A workaround option's plan, and whether it can be picked (P-6, AM-1, AM-3;
docs/design/scenarios.md § Investigation, answers and workarounds).

Each step of an option an agent proposed is planned as a scenario step is, with origin
``agent``: its action resolved (a bare name in the run's pack), its inputs and endpoints in the
run's environment, its content hash and draft state, and the policy's decision. An unresolved
action or inputs that do not fit are a ``deny`` with the problem. An option holding a ``deny`` (a
draft action included: ``needs acceptance``) cannot be picked (``pick_refusal``). Picking answers
its steps' asks. A step whose plan differs from the plan shown (``plan_changed``,
``changed_step``) is never run on that pick: at pick time the pick is refused and nothing is
recorded; at run time (a pick recorded earlier, the plan changed since) the workaround fails and
a new investigation opens, one of the scenario run's ``MAX_INVESTIGATIONS``.

``pick_problem`` is the check on an answer every entry point shares (``hub workflow
respond|decide`` and hub web): a ``pick`` of an investigation gate must name an option of the
investigation's latest proposal (``option_refusal``: it can be picked and its plan is still the
one shown); anything else passes. ``accept_command`` is the commit line a draft action needs
(AM-5: the screen shows it, nothing commits from there).
"""

import shlex
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import (
    Decision,
    Effect,
    PolicyDecision,
    ReasonKind,
    decide,
    deny_reason,
    find_environment,
)
from agent_hub.core.scenarios.action_call import ActionCallError, plan_action_call
from agent_hub.core.scenarios.action_catalog import ActionEntry, ActionRefError, resolve_action
from agent_hub.core.scenarios.investigation import PICK, ProposedStep
from agent_hub.core.scenarios.policy_gates import recorded_gate_kinds
from agent_hub.core.scenarios.run_record import OptionView, fold_records


class StepPlan(BaseModel):
    """One option step's plan: ``index`` from 1, the action as resolved (or as given when it
    is not), and ``problem`` when it could not be planned (then the decision is ``deny``)."""

    model_config = ConfigDict(frozen=True)

    index: int
    action: str
    effect: Effect | None = None
    content_hash: str | None = None
    draft: bool = False
    decision: Decision
    reason_kind: ReasonKind | None = None
    problem: str | None = None
    inputs: Mapping[str, JsonValue] = {}
    endpoint: Mapping[str, Mapping[str, JsonValue]] = {}


def plan_option(
    steps: Sequence[ProposedStep],
    *,
    entries: Iterable[ActionEntry],
    pack: str,
    view: EffectiveEnvironments,
    environment: str,
) -> tuple[StepPlan, ...]:
    """The plan of each of ``steps`` in ``environment``, origin ``agent``."""
    entries = tuple(entries)
    declared = find_environment(view, environment)
    planned: list[StepPlan] = []
    for index, step in enumerate(steps, 1):
        try:
            entry = resolve_action(entries, step.action, pack=pack)
        except ActionRefError as error:
            planned.append(
                StepPlan(index=index, action=step.action, decision="deny", problem=str(error))
            )
            continue
        decision = decide(declared, entry.document.effect, "agent", draft=entry.draft)
        found = StepPlan(
            index=index,
            action=entry.ref,
            effect=entry.document.effect,
            content_hash=entry.content_hash,
            draft=entry.draft,
            decision=decision.decision,
            reason_kind=decision.reason_kind,
        )
        try:
            call = plan_action_call(entry.document, step.inputs, environment=environment, view=view)
        except ActionCallError as error:
            found = found.model_copy(update={"decision": "deny", "problem": str(error)})
        else:
            found = found.model_copy(
                update={"inputs": dict(call.inputs), "endpoint": dict(call.endpoint)}
            )
        planned.append(found)
    return tuple(planned)


def pick_refusal(plan: Sequence[StepPlan]) -> StepPlan | None:
    """The first step that keeps the option from being picked (a ``deny``); ``None`` when it
    can be picked."""
    return next((step for step in plan if step.decision == "deny"), None)


def needs_acceptance(plan: Sequence[StepPlan]) -> bool:
    """Whether a step runs a draft action (it needs committing first)."""
    return any(step.draft for step in plan)


def plan_changed(shown: Sequence[Mapping[str, JsonValue]], now: Sequence[StepPlan]) -> bool:
    """Whether ``now`` differs from the plan ``shown`` (as recorded with the proposal)."""
    recorded = [step.model_dump(mode="json") for step in now]
    return [dict(step) for step in shown] != recorded


def changed_step(
    shown: Sequence[Mapping[str, JsonValue]], now: Sequence[StepPlan]
) -> StepPlan | None:
    """The first step of ``now`` whose plan differs from ``shown``'s; ``None`` when none."""
    for index, step in enumerate(now):
        if index >= len(shown) or dict(shown[index]) != step.model_dump(mode="json"):
            return step
    return None


def step_refusal(step: StepPlan, *, view: EffectiveEnvironments, environment: str) -> str:
    """Why ``step`` keeps its option from being picked, in plain words."""
    if step.problem is not None or step.effect is None or step.reason_kind is None:
        reason = step.problem or "cannot be planned"
    else:
        declared = find_environment(view, environment)
        decided = PolicyDecision(decision=step.decision, reason_kind=step.reason_kind)
        reason = deny_reason(
            decided,
            effect=step.effect,
            environment=environment,
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


class OptionPlanner(Protocol):
    """What an option is planned against now: the hub's actions as read and its effective
    environments, in the run's environment and pack."""

    def option(self, steps: Sequence[ProposedStep]) -> tuple[StepPlan, ...]:
        """The plan of ``steps``, origin ``agent``."""
        ...

    def refusal(self, step: StepPlan) -> str:
        """Why ``step`` keeps its option from being picked (``step_refusal``)."""
        ...


def option_refusal(option: OptionView, planner: OptionPlanner) -> str | None:
    """Why ``option`` cannot be picked now (a ``deny`` step, a draft action included, or a plan
    that changed since it was shown); ``None`` when it can."""
    now = planner.option(proposed_steps(option))
    if (refused := pick_refusal(now)) is not None:
        return f"option {option.option_id} cannot be picked: {planner.refusal(refused)}"
    if (changed := changed_step(option.plan, now)) is not None:
        return (
            f"option {option.option_id} cannot be picked: the plan of step {changed.index}"
            f" ({changed.action}) changed since it was shown; ask for a new proposal"
        )
    return None


def pick_problem(  # noqa: PLR0913 -- the gate and the answer, all keyword-only
    records: Sequence[Mapping[str, JsonValue]],
    *,
    node: str,
    attempt: int,
    choice: str | None,
    text: str | None,
    planner: Callable[[], OptionPlanner],
) -> str | None:
    """Why an answer to the run's gate ``node`` (``attempt``) cannot stand: a ``pick`` of an
    investigation gate naming no option of its latest proposal, an option that cannot be
    picked, or one whose plan changed since it was shown. ``None`` for any other answer or gate,
    which the record alone judges (E-10). ``planner`` is asked only for a pick."""
    if recorded_gate_kinds(records).get(node) != "investigation" or choice != PICK:
        return None
    view = fold_records(records)
    found = next(
        (item for item in view.investigations if (item.gate, item.number) == (node, attempt)),
        None,
    )
    proposal = None if found is None else found.proposal
    if proposal is None:
        return "no option was proposed yet: retry, stop, or wait for a proposal"
    option = proposal.option((text or "").strip())
    if option is None:
        known = ", ".join(item.option_id for item in proposal.options) or "none"
        return f"pick names an option as its text: one of {known}"
    return option_refusal(option, planner())


def accept_command(paths: Iterable[str], action: str) -> str:
    """The commit that accepts a draft action: its files added and committed in the hub
    checkout (a local commit suffices), each path quoted for a POSIX shell."""
    added = " ".join(shlex.quote(path) for path in paths)
    message = shlex.quote(f"Accept action {action}")
    return f"git add -- {added} && git commit -m {message}"
