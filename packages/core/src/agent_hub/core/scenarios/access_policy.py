"""The access policy: whether an action may run (docs/design/scenarios.md § Policy).

``decide`` is the one place the table lives. It takes the *effective* environment, the one
``effective_environments`` built from ``hub.json`` and ``hub.local.json``, so a local file that
tightens ``access`` tightens the decision and can never loosen it. No key and no flag turns an
``ask`` into an ``allow``: nothing here takes one.
"""

from collections.abc import Mapping
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    SourcedEnvironment,
)
from agent_hub.core.hub_config.environments import Access

Effect = Literal["read", "write", "destroy"]
# Who proposed the step: a committed document, a person in a terminal, or an agent.
Origin = Literal["author", "human", "agent"]
Decision = Literal["allow", "ask", "deny"]
# Why: ``read_only`` is the command's own refusal of an agent's write (``hub action run``).
ReasonKind = Literal["undeclared", "production", "table", "agent_origin", "draft", "read_only"]

# The table's rows for a declared, non-production environment.
_TABLE: Final[Mapping[Access, Mapping[Effect, Decision]]] = {
    "read": {"read": "allow", "write": "deny", "destroy": "deny"},
    "ask": {"read": "allow", "write": "ask", "destroy": "ask"},
    "write": {"read": "allow", "write": "allow", "destroy": "ask"},
}


class PolicyDecision(BaseModel):
    """A decision and the kind of reason behind it (recorded as ``policy.decision``)."""

    model_config = ConfigDict(frozen=True)

    decision: Decision
    reason_kind: ReasonKind


def decide(
    environment: SourcedEnvironment | None,
    effect: Effect,
    origin: Origin,
    *,
    draft: bool = False,
) -> PolicyDecision:
    """The decision for an action of ``effect`` proposed by ``origin`` in ``environment``.

    ``None`` is an environment declared in neither file. A draft action is denied whatever
    the table says; production denies every write and destroy; origin ``agent`` turns an
    ``allow`` of a write or destroy into ``ask``.
    """
    if draft:
        return PolicyDecision(decision="deny", reason_kind="draft")
    if environment is None:
        return PolicyDecision(decision="deny", reason_kind="undeclared")
    if environment.production and effect != "read":
        return PolicyDecision(decision="deny", reason_kind="production")
    decision = _TABLE[environment.access][effect]
    if decision == "allow" and effect != "read" and origin == "agent":
        return PolicyDecision(decision="ask", reason_kind="agent_origin")
    return PolicyDecision(decision=decision, reason_kind="table")


def find_environment(view: EffectiveEnvironments, name: str) -> SourcedEnvironment | None:
    """The effective environment ``name`` (its access as ``hub.local.json`` tightened it), or
    ``None`` when neither file declares it."""
    return next(
        (environment for environment in view.environments if environment.name == name), None
    )
