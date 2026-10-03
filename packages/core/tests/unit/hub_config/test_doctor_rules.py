from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_config.doctor_rules import (
    CONFIG_SCHEMA_RULE,
    MAX_MIN_LINE_LENGTH,
    RULE_IDS,
    RULE_MODULES,
    DoctorRules,
)
from agent_hub.core.hub_config.model import HubConfig, Modules
from agent_hub.core.testing.builders import a_hub_document

# Keep in sync with docs/design/hub-doctor.md § Rules.
RULE_TABLE_IDS = [
    "config.schema",
    "platform.version",
    "lock.drift",
    "links.dead",
    "instructions.size",
    "instructions.refs",
    "instructions.duplicates",
    "rules.frontmatter",
    "settings.valid",
    "settings.weakening",
    "permissions.bypass",
    "secrets.config",
    "mcp.pinned",
    "attribution.ai",
    "brain.leak",
    "hooks.guard-extension",
    "makefile.override",
    "features.tracker",
    "bench.tasks",
    "config.identity",
]
CONFIGURABLE_IDS = [rule_id for rule_id in RULE_TABLE_IDS if rule_id != "config.schema"]


def error_types(rules: dict[str, Any]) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        DoctorRules.model_validate(rules)
    return [(error["loc"], error["type"]) for error in caught.value.errors()]


def test_matches_rule_table_when_ids_listed() -> None:
    assert len(RULE_IDS) == len(set(RULE_IDS))
    assert set(RULE_IDS) == set(RULE_TABLE_IDS)
    assert RULE_MODULES == {"bench.tasks": "bench"}
    assert {field.alias for field in DoctorRules.model_fields.values()} == (
        set(RULE_IDS) - {CONFIG_SCHEMA_RULE}
    )
    module_ids = {field.alias or name for name, field in Modules.model_fields.items()}
    assert set(RULE_MODULES.values()) <= module_ids


@pytest.mark.parametrize("rule_id", CONFIGURABLE_IDS)
def test_accepts_rule_when_disabled(rule_id: str) -> None:
    rules = DoctorRules.model_validate({rule_id: {"enabled": False}})

    assert rules.model_dump(mode="json", exclude_none=True) == {rule_id: {"enabled": False}}


@pytest.mark.parametrize("rule_id", CONFIGURABLE_IDS)
def test_accepts_rule_when_severity_overridden(rule_id: str) -> None:
    rules = DoctorRules.model_validate({rule_id: {"severity": "warning"}})

    assert rules.model_dump(mode="json", exclude_none=True) == {
        rule_id: {"enabled": True, "severity": "warning"}
    }


@pytest.mark.parametrize(
    "entry", [{}, {"enabled": True}, {"enabled": False}, {"severity": "warning"}]
)
def test_rejects_config_schema_when_any_entry_given(entry: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as caught:
        DoctorRules.model_validate({"config.schema": entry})

    [error] = caught.value.errors()
    assert (error["loc"], error["msg"]) == (
        ("config.schema",),
        "config.schema always runs as an error; remove it",
    )


def test_rejects_rule_when_id_unknown() -> None:
    assert error_types({"instructions.length": {}}) == [
        (("instructions.length",), "extra_forbidden")
    ]


def test_rejects_rule_when_option_unknown() -> None:
    assert error_types({"links.dead": {"max": 1}}) == [(("links.dead", "max"), "extra_forbidden")]


def test_rejects_severity_when_not_known_level() -> None:
    assert error_types({"links.dead": {"severity": "fatal"}}) == [
        (("links.dead", "severity"), "enum")
    ]


def test_rejects_enabled_when_not_boolean() -> None:
    assert error_types({"links.dead": {"enabled": "yes"}}) == [
        (("links.dead", "enabled"), "bool_type")
    ]


def test_accepts_options_when_phase_one_options_valid() -> None:
    rules = DoctorRules.model_validate(
        {
            "instructions.size": {"max_lines": {"AGENTS.md": 120, ".claude/rules/*.md": 60}},
            "brain.leak": {"min_line_length": 80},
        }
    )

    assert rules.model_dump(mode="json", exclude_none=True) == {
        "instructions.size": {
            "enabled": True,
            "max_lines": {"AGENTS.md": 120, ".claude/rules/*.md": 60},
        },
        "brain.leak": {"enabled": True, "min_line_length": 80},
    }


@pytest.mark.parametrize("limit", [0, -1, "120", 1.0, True])
def test_rejects_max_lines_when_not_positive_integer(limit: object) -> None:
    locs = [
        loc for loc, _ in error_types({"instructions.size": {"max_lines": {"AGENTS.md": limit}}})
    ]

    assert locs == [("instructions.size", "max_lines", "AGENTS.md")]


@pytest.mark.parametrize("length", [0, -5, "80"])
def test_rejects_min_line_length_when_not_positive(length: object) -> None:
    locs = [loc for loc, _ in error_types({"brain.leak": {"min_line_length": length}})]

    assert locs == [("brain.leak", "min_line_length")]


def test_rejects_min_line_length_when_above_bound() -> None:
    within = DoctorRules.model_validate({"brain.leak": {"min_line_length": MAX_MIN_LINE_LENGTH}})
    above = {"brain.leak": {"min_line_length": MAX_MIN_LINE_LENGTH + 1}}

    assert within.brain_leak is not None
    assert within.brain_leak.min_line_length == MAX_MIN_LINE_LENGTH
    assert error_types(above) == [(("brain.leak", "min_line_length"), "less_than_equal")]


@pytest.mark.parametrize(
    "rule_id", [rule_id for rule_id in CONFIGURABLE_IDS if rule_id != "instructions.size"]
)
def test_rejects_max_lines_when_on_other_rule(rule_id: str) -> None:
    assert error_types({rule_id: {"max_lines": {"AGENTS.md": 120}}}) == [
        ((rule_id, "max_lines"), "extra_forbidden")
    ]


def test_drops_comment_key_when_inside_max_lines() -> None:
    rules = DoctorRules.model_validate(
        {"instructions.size": {"max_lines": {"_why": "long index", "AGENTS.md": 120}}}
    )

    assert rules.instructions_size is not None
    assert rules.instructions_size.max_lines == {"AGENTS.md": 120}


@pytest.mark.parametrize("limits", [[], "AGENTS.md", 120])
def test_rejects_max_lines_when_not_object(limits: object) -> None:
    assert error_types({"instructions.size": {"max_lines": limits}}) == [
        (("instructions.size", "max_lines"), "dict_type")
    ]


def test_rejects_max_lines_when_file_key_empty() -> None:
    assert error_types({"instructions.size": {"max_lines": {"": 120}}}) == [
        (("instructions.size", "max_lines", "", "[key]"), "string_too_short")
    ]


def a_config_with_limits(max_lines: dict[str, int]) -> HubConfig:
    document = a_hub_document()
    document["doctor"] = {"rules": {"instructions.size": {"max_lines": max_lines}}}
    return HubConfig.model_validate(document)


def config_error_types(max_lines: dict[str, int]) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        a_config_with_limits(max_lines)
    return [(error["loc"], error["type"]) for error in caught.value.errors()]


MAX_LINES_LOC = ("doctor", "rules", "instructions.size", "max_lines")


def test_bounds_max_lines_key_when_longer_than_limit() -> None:
    # E30: a key is 1 to 1024 characters (fnmatch.translate is quadratic on a long key).
    longest = "a" * 1024
    too_long = longest + "a"

    config = a_config_with_limits({longest: 120})

    assert config.doctor.rules.instructions_size is not None
    assert config.doctor.rules.instructions_size.max_lines == {longest: 120}
    assert config_error_types({too_long: 120}) == [
        ((*MAX_LINES_LOC, too_long, "[key]"), "string_too_long")
    ]


def test_bounds_max_lines_map_when_more_keys_than_limit() -> None:
    # E30: at most 256 keys (each glob key is tried on each instruction file); comment keys
    # are dropped first, so they do not count.
    most = {f"f{number}.md": 120 for number in range(256)}
    too_many = {**most, "one-more.md": 120}

    config = a_config_with_limits({"_why": "comment", **most})

    assert config.doctor.rules.instructions_size is not None
    assert config.doctor.rules.instructions_size.max_lines == most
    assert config_error_types(too_many) == [(MAX_LINES_LOC, "too_long")]
