"""A workaround option's plan, and whether it can be picked (P-6, AM-1, AM-3;
docs/design/scenarios.md § Investigation, answers and workarounds).

Each step of an option an agent proposed is planned as a scenario step is, with origin
``agent``: its action resolved (a bare name in the run's pack), its inputs and endpoints in the
run's environment, its content hash and draft state, and the policy's decision. An unresolved
action or inputs that do not fit are a ``deny`` with the problem. An option holding a ``deny`` (a
draft action included: ``needs acceptance``) cannot be picked (``pick_refusal``). Picking answers
its steps' asks. A step whose plan differs, when it is picked or when it runs, from the plan
shown (``plan_changed``) is not run on that pick: the person is asked again.
"""

from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import (
    Decision,
    Effect,
    ReasonKind,
    decide,
    find_environment,
)
from agent_hub.core.scenarios.action_call import ActionCallError, plan_action_call
from agent_hub.core.scenarios.action_catalog import ActionEntry, ActionRefError, resolve_action
from agent_hub.core.scenarios.investigation import ProposedStep


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
