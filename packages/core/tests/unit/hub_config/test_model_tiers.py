from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.model_tiers import (
    AGENT_NAMES,
    DEFAULT_TIER_MODELS,
    MODEL_NAME_PATTERN,
    TIERS,
    Models,
)
from agent_hub.core.hub_config.problems import json_path
from agent_hub.core.testing.builders import a_hub_document, a_models_document


def with_models(models: object) -> dict[str, Any]:
    document = a_hub_document()
    document["models"] = models
    return document


def error_paths(document: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)
    return [json_path(error["loc"]) for error in caught.value.errors()]


def test_resolves_default_models_when_models_absent() -> None:
    config = HubConfig.model_validate(a_hub_document())

    assert config.models == Models()
    assert {tier: config.models.model_for(tier) for tier in TIERS} == {
        "small": "haiku",
        "medium": "sonnet",
        "large": "opus",
    }
    assert all(config.models.agent_tier(name) is None for name in AGENT_NAMES)


def test_keeps_defaults_in_order_when_tiers_listed() -> None:
    assert TIERS == ("small", "medium", "large")
    assert tuple(DEFAULT_TIER_MODELS) == TIERS


def test_resolves_configured_models_when_tiers_set() -> None:
    config = HubConfig.model_validate(a_models_document())

    assert config.models.model_for("large") == "claude-opus-4-1"
    assert config.models.model_for("medium") == "sonnet"
    # Not configured: the default.
    assert config.models.model_for("small") == "haiku"


def test_fills_missing_tiers_from_defaults_when_tiers_partial() -> None:
    config = HubConfig.model_validate(with_models({"tiers": {"small": "inherit"}}))

    assert config.models.model_for("small") == "inherit"
    assert config.models.model_for("medium") == "sonnet"
    assert config.models.model_for("large") == "opus"


def test_returns_override_when_agent_tier_set() -> None:
    config = HubConfig.model_validate(
        with_models({"agents": {"researcher": "large", "quality-reviewer": "small"}})
    )

    assert config.models.agent_tier("researcher") == "large"
    assert config.models.agent_tier("quality-reviewer") == "small"
    assert config.models.agent_tier("evaluator") is None


def test_lists_plugin_agents_when_agent_names_read() -> None:
    assert AGENT_NAMES == (
        "architect",
        "evaluator",
        "planner",
        "quality-reviewer",
        "requirements-analyst",
        "researcher",
        "spec-reviewer",
        "ux-designer",
    )


@pytest.mark.parametrize("models", [{}, {"tiers": {}, "agents": {}}, {"_note": "x"}])
def test_equals_absent_key_when_models_empty(models: dict[str, Any]) -> None:
    assert HubConfig.model_validate(with_models(models)).models == Models()


def test_ignores_comment_keys_when_each_level_holds_one() -> None:
    models = {
        "_note": "x",
        "tiers": {"_note": "x", "large": "opus"},
        "agents": {"_note": "x", "planner": "small"},
    }

    config = HubConfig.model_validate(with_models(models))

    assert config.models.model_for("large") == "opus"
    assert config.models.agent_tier("planner") == "small"


@pytest.mark.parametrize(
    ("models", "path"),
    [
        ({"tiers": {"huge": "opus"}}, "models.tiers.huge"),
        ({"agents": {"researcher": "xl"}}, "models.agents.researcher"),
        ({"agents": {"researcher": "opus"}}, "models.agents.researcher"),
        ({"agents": {"reseacher": "large"}}, "models.agents.reseacher"),
        ({"run": "medium"}, "models.run"),
        ({"tiers": {"large": None}}, "models.tiers.large"),
        ("large", "models"),
    ],
    ids=[
        "unknown-tier-key",
        "unknown-tier-value",
        "model-as-tier",
        "unknown-agent",
        "unknown-key",
        "null",
        "not-an-object",
    ],
)
def test_rejects_models_when_tier_or_key_unknown(models: object, path: str) -> None:
    assert error_paths(with_models(models)) == [path]


@pytest.mark.parametrize(
    "name",
    ["", "a b", "opus[1m]", "us.anthropic.claude:0", "x" * 65, "a\nb", "a#b", 'a"b'],
    ids=["empty", "space", "brackets", "colon", "too-long", "newline", "hash", "quote"],
)
def test_rejects_model_name_when_pattern_fails(name: str) -> None:
    assert error_paths(with_models({"tiers": {"medium": name}})) == ["models.tiers.medium"]


@pytest.mark.parametrize(
    "name", ["haiku", "inherit", "claude-opus-4-1-20250805", "x" * 64, "a.b_c-d"]
)
def test_accepts_model_name_when_pattern_holds(name: str) -> None:
    config = HubConfig.model_validate(with_models({"tiers": {"medium": name}}))

    assert config.models.model_for("medium") == name


def test_matches_run_pattern_when_pattern_read() -> None:
    assert MODEL_NAME_PATTERN.pattern == r"[A-Za-z0-9._-]{1,64}"
