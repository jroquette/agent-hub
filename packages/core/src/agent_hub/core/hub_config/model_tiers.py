"""Model tiers: the optional ``models`` key of ``hub.json`` (docs/design/project-config.md).

Three closed tiers map to model names, which the generator renders into each plugin agent's
``model:`` frontmatter and ``hub run`` passes to its implementing session (``medium``). Each
agent's default tier stays in its template; ``models.agents`` overrides it for one of the
plugin's agents. A closed set of tiers and agents keeps every check in the exported schema: an
unknown tier or agent is a schema error, which ``hub doctor`` reports as ``config.schema``.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Final, Literal, cast, get_args

from pydantic import Field

from agent_hub.core.hub_config.config_object import ConfigObject, absent_by_default

Tier = Literal["small", "medium", "large"]
TIERS: Final[tuple[Tier, ...]] = get_args(Tier)

# Also what ``hub run --model`` accepts: safe unquoted in YAML frontmatter and in an argv.
MODEL_NAME_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,64}")
ModelName = Annotated[str, Field(pattern=rf"^{MODEL_NAME_PATTERN.pattern}$")]

# Each tier's model when ``models.tiers`` leaves it out: the models the templates pinned before
# tiers existed, so a hub without ``models`` keeps its bytes.
DEFAULT_TIER_MODELS: Final[Mapping[Tier, str]] = MappingProxyType(
    {"small": "haiku", "medium": "sonnet", "large": "opus"}
)
# The tier of ``hub run``'s implementing session.
RUN_TIER: Final[Tier] = "medium"


class ModelTiers(ConfigObject):
    """The model name of each tier; an absent tier takes its default."""

    small: ModelName | None = absent_by_default(description="Default: haiku.")
    medium: ModelName | None = absent_by_default(description="Default: sonnet.")
    large: ModelName | None = absent_by_default(description="Default: opus.")


class AgentTiers(ConfigObject):
    """The tier of each plugin agent that does not keep its template's tier."""

    architect: Tier | None = absent_by_default()
    evaluator: Tier | None = absent_by_default()
    planner: Tier | None = absent_by_default()
    quality_reviewer: Tier | None = absent_by_default(alias="quality-reviewer")
    requirements_analyst: Tier | None = absent_by_default(alias="requirements-analyst")
    researcher: Tier | None = absent_by_default()
    spec_reviewer: Tier | None = absent_by_default(alias="spec-reviewer")


# The plugin's agents by file stem, as ``models.agents`` names them. Derived from
# ``AgentTiers``; a generator test keeps it equal to the agent templates.
AGENT_NAMES: Final[tuple[str, ...]] = tuple(
    field.alias or name for name, field in AgentTiers.model_fields.items()
)


class Models(ConfigObject):
    """Which model each tier names, and which agents leave their template's tier."""

    # Factories, not instances, as in ``HubConfig``.
    tiers: ModelTiers = Field(default_factory=ModelTiers)
    agents: AgentTiers = Field(default_factory=AgentTiers)

    def model_for(self, tier: Tier) -> str:
        """The model name of ``tier``: the configured one, else its default."""
        configured = cast("str | None", getattr(self.tiers, tier))
        return configured if configured is not None else DEFAULT_TIER_MODELS[tier]

    def agent_tier(self, agent: str) -> Tier | None:
        """The tier ``models.agents`` sets for ``agent`` (a file stem); None keeps the template."""
        return cast("Tier | None", self.agents.model_dump(by_alias=True).get(agent))
