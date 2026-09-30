"""The rules this release of ``hub doctor`` ships, in ``RULE_IDS`` order.

A known id missing here is "not in this release" (docs/design/hub-doctor.md § Rules); each
release that adds rules appends them.
"""

from typing import Final

from agent_hub.core.doctor.config_rules import CONFIG_SCHEMA, PLATFORM_VERSION
from agent_hub.core.doctor.features_rule import FEATURES_TRACKER
from agent_hub.core.doctor.finding import Rule
from agent_hub.core.doctor.guard_extension_rule import GUARD_EXTENSION
from agent_hub.core.doctor.lock_rules import LOCK_DRIFT
from agent_hub.core.doctor.makefile_rules import MAKEFILE_OVERRIDE
from agent_hub.core.doctor.settings_rules import SETTINGS_WEAKENING

REGISTRY: Final[tuple[Rule, ...]] = (
    CONFIG_SCHEMA,
    PLATFORM_VERSION,
    LOCK_DRIFT,
    SETTINGS_WEAKENING,
    GUARD_EXTENSION,
    MAKEFILE_OVERRIDE,
    FEATURES_TRACKER,
)
