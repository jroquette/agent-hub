"""The closed ``hub doctor`` rule ids and their settings in ``hub.json`` → ``doctor.rules``.

The ids are those of docs/design/hub-doctor.md § Rules; ``hub doctor`` (AGH-11) reuses them.
"""

from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Final

from pydantic import BeforeValidator, Field, StrictBool, StrictInt

from agent_hub.core.hub_config.config_object import (
    COMMENT_KEYS_SCHEMA,
    ConfigObject,
    absent_by_default,
    drop_comment_keys,
)

CONFIG_SCHEMA_RULE: Final = "config.schema"
PLATFORM_VERSION_RULE: Final = "platform.version"
LOCK_DRIFT_RULE: Final = "lock.drift"
LINKS_DEAD_RULE: Final = "links.dead"
INSTRUCTIONS_SIZE_RULE: Final = "instructions.size"
INSTRUCTIONS_REFS_RULE: Final = "instructions.refs"
INSTRUCTIONS_DUPLICATES_RULE: Final = "instructions.duplicates"
RULES_FRONTMATTER_RULE: Final = "rules.frontmatter"
SETTINGS_VALID_RULE: Final = "settings.valid"
SETTINGS_WEAKENING_RULE: Final = "settings.weakening"
PERMISSIONS_BYPASS_RULE: Final = "permissions.bypass"
SECRETS_CONFIG_RULE: Final = "secrets.config"
MCP_PINNED_RULE: Final = "mcp.pinned"
ATTRIBUTION_AI_RULE: Final = "attribution.ai"
BRAIN_LEAK_RULE: Final = "brain.leak"
GUARD_EXTENSION_RULE: Final = "hooks.guard-extension"
MAKEFILE_OVERRIDE_RULE: Final = "makefile.override"
FEATURES_TRACKER_RULE: Final = "features.tracker"
BENCH_TASKS_RULE: Final = "bench.tasks"

RULE_IDS: Final = (
    CONFIG_SCHEMA_RULE,
    PLATFORM_VERSION_RULE,
    LOCK_DRIFT_RULE,
    LINKS_DEAD_RULE,
    INSTRUCTIONS_SIZE_RULE,
    INSTRUCTIONS_REFS_RULE,
    INSTRUCTIONS_DUPLICATES_RULE,
    RULES_FRONTMATTER_RULE,
    SETTINGS_VALID_RULE,
    SETTINGS_WEAKENING_RULE,
    PERMISSIONS_BYPASS_RULE,
    SECRETS_CONFIG_RULE,
    MCP_PINNED_RULE,
    ATTRIBUTION_AI_RULE,
    BRAIN_LEAK_RULE,
    GUARD_EXTENSION_RULE,
    MAKEFILE_OVERRIDE_RULE,
    FEATURES_TRACKER_RULE,
    BENCH_TASKS_RULE,
)

# The rules a module owns: they run and may be configured only when the module is selected.
RULE_MODULES: Final = MappingProxyType({BENCH_TASKS_RULE: "bench"})


class Severity(StrEnum):
    """The level of a finding."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class RuleSettings(ConfigObject):
    """How a project tunes one rule: whether it runs, and the level of its findings."""

    enabled: StrictBool = True
    severity: Severity | None = absent_by_default()


# A JSON integer above zero: lax mode would take "120", true and 1.0.
PositiveInt = Annotated[StrictInt, Field(gt=0)]


def drop_map_comment_keys(value: object) -> object:
    """Drop the ``_`` keys of a free-key map, as every fixed-key object does (Q6)."""
    return drop_comment_keys(value) if isinstance(value, dict) else value


# E30: scale guards. ``fnmatch.translate`` is quadratic on a long key, and each glob key is tried
# on each instruction file; comment keys are dropped first, so they count toward neither.
MAX_LINES_KEY_LENGTH: Final = 1024
MAX_LINES_KEYS: Final = 256

# A file name or glob mapped to its line limit, merged over the rule's defaults.
LineLimits = Annotated[
    dict[Annotated[str, Field(min_length=1, max_length=MAX_LINES_KEY_LENGTH)], PositiveInt],
    Field(max_length=MAX_LINES_KEYS),
    BeforeValidator(drop_map_comment_keys),
    # The schema says what the model does: a ``_`` key is a comment, not a limit.
    Field(json_schema_extra=COMMENT_KEYS_SCHEMA),
]


class InstructionsSizeSettings(RuleSettings):
    """``instructions.size``: the line limits of instruction files.

    ``max_lines`` stays a plain ``dict``, so frozen is shallow for the ``max_lines`` map.
    """

    max_lines: LineLimits | None = absent_by_default()


# A bar above any line a person writes checks nothing; the bound keeps a typo out (scale guard).
MAX_MIN_LINE_LENGTH: Final = 10_000


class BrainLeakSettings(RuleSettings):
    """``brain.leak``: the shortest trimmed brain line that counts as a leak."""

    min_line_length: Annotated[PositiveInt, Field(le=MAX_MIN_LINE_LENGTH)] | None = (
        absent_by_default()
    )


class DoctorRules(ConfigObject):
    """``doctor.rules``: one optional entry per rule id, except ``config.schema``."""

    rejected_keys = MappingProxyType(
        {CONFIG_SCHEMA_RULE: f"{CONFIG_SCHEMA_RULE} always runs as an error; remove it"}
    )

    platform_version: RuleSettings | None = absent_by_default(alias="platform.version")
    lock_drift: RuleSettings | None = absent_by_default(alias="lock.drift")
    links_dead: RuleSettings | None = absent_by_default(alias="links.dead")
    instructions_size: InstructionsSizeSettings | None = absent_by_default(
        alias="instructions.size"
    )
    instructions_refs: RuleSettings | None = absent_by_default(alias="instructions.refs")
    instructions_duplicates: RuleSettings | None = absent_by_default(
        alias="instructions.duplicates"
    )
    rules_frontmatter: RuleSettings | None = absent_by_default(alias="rules.frontmatter")
    settings_valid: RuleSettings | None = absent_by_default(alias="settings.valid")
    settings_weakening: RuleSettings | None = absent_by_default(alias="settings.weakening")
    permissions_bypass: RuleSettings | None = absent_by_default(alias="permissions.bypass")
    secrets_config: RuleSettings | None = absent_by_default(alias="secrets.config")
    mcp_pinned: RuleSettings | None = absent_by_default(alias="mcp.pinned")
    attribution_ai: RuleSettings | None = absent_by_default(alias="attribution.ai")
    brain_leak: BrainLeakSettings | None = absent_by_default(alias="brain.leak")
    hooks_guard_extension: RuleSettings | None = absent_by_default(alias="hooks.guard-extension")
    makefile_override: RuleSettings | None = absent_by_default(alias="makefile.override")
    features_tracker: RuleSettings | None = absent_by_default(alias="features.tracker")
    bench_tasks: RuleSettings | None = absent_by_default(alias="bench.tasks")
