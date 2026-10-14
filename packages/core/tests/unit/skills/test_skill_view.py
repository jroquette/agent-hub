import re
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_hub.core.errors import AgentHubError
from agent_hub.core.skills.skill_view import (
    ITEM_NAME,
    KNOWN_AGENT_KEYS,
    KNOWN_SKILL_KEYS,
    SEVERITY,
    CatalogItem,
    DiagnosticCode,
    DiagnosticSeverity,
    FrontmatterPair,
    ItemKind,
    Mode,
    Origin,
    SkillFileTooLargeError,
    Usage,
    bare_name,
    item_id,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/feature", "feature"),
        ("feature", "feature"),
        ("hub-workflow:feature", "feature"),
        ("/hub-workflow:feature", "feature"),
        ("evaluator", "evaluator"),
    ],
)
def test_strips_slash_and_plugin_prefix_when_name_normalised(raw: str, expected: str) -> None:
    assert bare_name(raw) == expected


def test_refuses_item_when_field_unknown() -> None:
    fields = {
        "id": "skill/hub-workflow/alpha",
        "kind": "skill",
        "source": "hub-workflow",
        "name": "alpha",
        "description": "Alpha skill.",
        "origin": "managed",
        "mode": "both",
        "invocation": "/alpha",
        "source_path": "plugin/hub-workflow/skills/alpha/SKILL.md",
        "diagnostics_count": 0,
        "usage": Usage(count=0, user_count=0, model_count=0, last_used_at=None),
    }

    item = CatalogItem.model_validate(fields)
    with pytest.raises(ValidationError):
        CatalogItem.model_validate(fields | {"path": "/home/demo/x"})

    assert (item.kind, item.origin, item.mode) == (ItemKind.SKILL, Origin.MANAGED, Mode.BOTH)
    assert item.linked_from == ()
    assert item.active is True
    assert item.state is None


def test_builds_id_when_kind_source_name_given() -> None:
    assert item_id(ItemKind.SKILL, "hub-workflow", "alpha") == "skill/hub-workflow/alpha"
    assert item_id(ItemKind.HOOK, "settings", "settings-pretooluse-1") == (
        "hook/settings/settings-pretooluse-1"
    )


def test_matches_item_names_when_pattern_applied() -> None:
    pattern = re.compile(ITEM_NAME)

    assert pattern.fullmatch("local-one_2")
    assert pattern.fullmatch("a" * 128)
    for refused in ("", "a.b", "a/b", "..", "a\\b", "a" * 129):
        assert not pattern.fullmatch(refused), refused


def test_gives_every_code_a_severity_when_table_read() -> None:
    assert set(SEVERITY) == set(DiagnosticCode)
    assert SEVERITY[DiagnosticCode.NAME_INVALID] is DiagnosticSeverity.WARNING
    assert SEVERITY[DiagnosticCode.UNKNOWN_KEY] is DiagnosticSeverity.INFO


def test_lists_spec_keys_when_known_keys_read() -> None:
    assert {"name", "description", "argument-hint", "disable-model-invocation"} <= KNOWN_SKILL_KEYS
    assert {"name", "tools", "model", "disallowedTools"} <= KNOWN_AGENT_KEYS
    assert "tools" not in KNOWN_SKILL_KEYS


def test_keeps_metadata_map_when_pair_value_is_mapping() -> None:
    pair = FrontmatterPair(key="metadata", value={"author": "demo"}, known=True)

    assert pair.value == {"author": "demo"}


def test_names_limit_when_skill_file_too_large() -> None:
    error = SkillFileTooLargeError(limit=262_144, size=300_000)

    assert isinstance(error, AgentHubError)
    assert (error.limit, error.size) == (262_144, 300_000)


def test_serializes_usage_time_when_used() -> None:
    usage = Usage(
        count=3, user_count=2, model_count=1, last_used_at=datetime(2026, 10, 1, tzinfo=UTC)
    )

    assert usage.model_dump(mode="json")["last_used_at"] == "2026-10-01T00:00:00.000Z"
