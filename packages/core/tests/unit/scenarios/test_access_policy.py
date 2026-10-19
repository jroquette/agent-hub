import itertools
from typing import Final

import pytest

from agent_hub.core.hub_config.effective_environments import SourcedEnvironment
from agent_hub.core.scenarios.access_policy import Effect, Origin, PolicyDecision, decide

EFFECTS: Final[tuple[Effect, ...]] = ("read", "write", "destroy")
ORIGINS: Final[tuple[Origin, ...]] = ("author", "human", "agent")
ENVIRONMENTS: Final = (
    "undeclared",
    "read",
    "ask",
    "write",
    "production-read",
    "production-ask",
    "production-write",
)

# The Policy table of docs/design/scenarios.md and its origin rule, written out by hand:
# (environment, effect) → (decision, reason) for origin author or human, then for origin agent.
POLICY_TABLE: Final = {
    ("undeclared", "read"): (("deny", "undeclared"), ("deny", "undeclared")),
    ("undeclared", "write"): (("deny", "undeclared"), ("deny", "undeclared")),
    ("undeclared", "destroy"): (("deny", "undeclared"), ("deny", "undeclared")),
    ("read", "read"): (("allow", "table"), ("allow", "table")),
    ("read", "write"): (("deny", "table"), ("deny", "table")),
    ("read", "destroy"): (("deny", "table"), ("deny", "table")),
    ("ask", "read"): (("allow", "table"), ("allow", "table")),
    ("ask", "write"): (("ask", "table"), ("ask", "table")),
    ("ask", "destroy"): (("ask", "table"), ("ask", "table")),
    ("write", "read"): (("allow", "table"), ("allow", "table")),
    ("write", "write"): (("allow", "table"), ("ask", "agent_origin")),
    ("write", "destroy"): (("ask", "table"), ("ask", "table")),
    ("production-read", "read"): (("allow", "table"), ("allow", "table")),
    ("production-read", "write"): (("deny", "production"), ("deny", "production")),
    ("production-read", "destroy"): (("deny", "production"), ("deny", "production")),
    ("production-ask", "read"): (("allow", "table"), ("allow", "table")),
    ("production-ask", "write"): (("deny", "production"), ("deny", "production")),
    ("production-ask", "destroy"): (("deny", "production"), ("deny", "production")),
    ("production-write", "read"): (("allow", "table"), ("allow", "table")),
    ("production-write", "write"): (("deny", "production"), ("deny", "production")),
    ("production-write", "destroy"): (("deny", "production"), ("deny", "production")),
}


def an_environment(key: str) -> SourcedEnvironment | None:
    if key == "undeclared":
        return None
    production, _, access = key.rpartition("-")
    return SourcedEnvironment(
        name="demo-env",
        access=access,
        production=production == "production",
        description=None,
        credentials=None,
        source="hub.json",
    )


@pytest.mark.parametrize(
    ("environment", "effect", "origin"), list(itertools.product(ENVIRONMENTS, EFFECTS, ORIGINS))
)
def test_returns_table_value_when_access_policy_combination_given(
    environment: str, effect: Effect, origin: Origin
) -> None:
    # AC-350.1: every combination, against the literal table above.
    by_person, by_agent = POLICY_TABLE[(environment, effect)]
    expected = by_agent if origin == "agent" else by_person

    decision = decide(an_environment(environment), effect, origin)

    assert decision == PolicyDecision(decision=expected[0], reason_kind=expected[1])


@pytest.mark.parametrize(
    ("environment", "effect", "origin"), list(itertools.product(ENVIRONMENTS, EFFECTS, ORIGINS))
)
def test_denies_when_access_policy_draft(environment: str, effect: Effect, origin: Origin) -> None:
    # AC-350.1: a draft action is denied whatever the table says.
    decision = decide(an_environment(environment), effect, origin, draft=True)

    assert decision == PolicyDecision(decision="deny", reason_kind="draft")
