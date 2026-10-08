"""The rules this release of ``hub doctor`` ships, in ``RULE_IDS`` order.

A known id missing here is "not in this release" (docs/design/hub-doctor.md § Rules); each
release that adds rules appends them.
"""

from typing import Final

from agent_hub.core.doctor.bench_rule import BENCH_TASKS
from agent_hub.core.doctor.brain_leak_rule import BRAIN_LEAK
from agent_hub.core.doctor.config_rules import CONFIG_IDENTITY, CONFIG_SCHEMA, PLATFORM_VERSION
from agent_hub.core.doctor.features_rule import FEATURES_TRACKER
from agent_hub.core.doctor.finding import Rule
from agent_hub.core.doctor.frontmatter_rule import RULES_FRONTMATTER
from agent_hub.core.doctor.guard_extension_rule import GUARD_EXTENSION
from agent_hub.core.doctor.instruction_rules import (
    INSTRUCTIONS_DUPLICATES,
    INSTRUCTIONS_REFS,
    INSTRUCTIONS_SIZE,
)
from agent_hub.core.doctor.links_rule import LINKS_DEAD
from agent_hub.core.doctor.lock_rules import LOCK_DRIFT
from agent_hub.core.doctor.makefile_rules import MAKEFILE_OVERRIDE
from agent_hub.core.doctor.permission_rules import MCP_PINNED, PERMISSIONS_BYPASS, SETTINGS_VALID
from agent_hub.core.doctor.repo_agents_rule import REPOS_AGENTS
from agent_hub.core.doctor.settings_rules import SETTINGS_WEAKENING
from agent_hub.core.doctor.text_rules import ATTRIBUTION_AI, SECRETS_CONFIG

REGISTRY: Final[tuple[Rule, ...]] = (
    CONFIG_SCHEMA,
    PLATFORM_VERSION,
    LOCK_DRIFT,
    LINKS_DEAD,
    INSTRUCTIONS_SIZE,
    INSTRUCTIONS_REFS,
    INSTRUCTIONS_DUPLICATES,
    RULES_FRONTMATTER,
    SETTINGS_VALID,
    SETTINGS_WEAKENING,
    PERMISSIONS_BYPASS,
    SECRETS_CONFIG,
    MCP_PINNED,
    ATTRIBUTION_AI,
    BRAIN_LEAK,
    GUARD_EXTENSION,
    MAKEFILE_OVERRIDE,
    FEATURES_TRACKER,
    BENCH_TASKS,
    CONFIG_IDENTITY,
    REPOS_AGENTS,
)
