import json
from collections.abc import Iterator
from typing import Any

from agent_hub.core.hub_config.doctor_rules import MAX_LINES_KEY_LENGTH, MAX_LINES_KEYS
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.platform_repository import PLATFORM_REPOSITORY_PATTERN
from agent_hub.core.hub_config.schema import export_schema_text, read_shipped_schema

COMMENT_KEYS = {"^_": {}}


def object_nodes(node: object, path: str = "$") -> Iterator[tuple[str, dict[str, Any]]]:
    """Every schema node with ``type: object``, with a readable path, root included."""
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from object_nodes(item, f"{path}[{index}]")
    elif isinstance(node, dict):
        if node.get("type") == "object":
            yield path, node
        for key, value in node.items():
            yield from object_nodes(value, f"{path}.{key}")


def test_matches_model_export_when_shipped_file_read() -> None:
    assert read_shipped_schema() == HubConfig.model_json_schema()


def test_forbids_extra_keys_when_object_has_fixed_keys() -> None:
    schema = read_shipped_schema()
    maps: list[tuple[str, dict[str, Any]]] = []

    for path, node in object_nodes(schema):
        assert node.get("patternProperties") == COMMENT_KEYS, path
        if "properties" in node:
            assert node["additionalProperties"] is False, path
        else:
            maps.append((path, node))

    [(path, max_lines)] = maps
    assert path.endswith(".InstructionsSizeSettings.properties.max_lines")
    # E30: the model's bounds, pinned by number in test_doctor_rules.py.
    assert max_lines["propertyNames"] == {"minLength": 1, "maxLength": MAX_LINES_KEY_LENGTH}
    assert max_lines["maxProperties"] == MAX_LINES_KEYS
    assert max_lines["additionalProperties"] == {"exclusiveMinimum": 0, "type": "integer"}


def test_declares_optional_schema_key_when_root_exported() -> None:
    schema = read_shipped_schema()

    assert schema["properties"]["$schema"] == {
        "type": "string",
        "minLength": 1,
        "pattern": "^[^\\x00-\\x1f\\x7f]+$",
    }
    assert "$schema" not in schema["required"]


def test_exports_same_text_when_called_twice() -> None:
    first = export_schema_text()

    assert export_schema_text() == first
    assert first.endswith("}\n")
    assert json.loads(first) == HubConfig.model_json_schema()


def test_describes_repo_branch_as_inherited_when_schema_exported() -> None:
    definitions = read_shipped_schema()["$defs"]
    repo = definitions["Repo"]
    project_branch = definitions["Project"]["properties"]["default_branch"]

    branch = repo["properties"]["default_branch"]

    assert "default_branch" not in repo["required"]
    assert branch["type"] == "string"
    assert branch["pattern"] == project_branch["pattern"]
    assert "default" not in branch
    assert "title" not in branch
    assert "anyOf" not in branch
    assert "project.default_branch" in branch["description"]


def test_leaves_identity_keys_optional_when_schema_exported() -> None:
    project = read_shipped_schema()["$defs"]["Project"]
    patterns = {
        "branch_prefix": "^[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*/$",
        "author_name": "^[^\\x00-\\x1f\\x7f]+$",
        "author_email": "^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$",
    }

    assert project["required"] == ["name", "hub_repo"]
    for key, pattern in patterns.items():
        node = project["properties"][key]
        assert node["type"] == "string", key
        assert node["pattern"] == pattern, key
        assert "default" not in node, key
        assert "title" not in node, key
        assert "anyOf" not in node, key
        assert "hub.local.json" in node["description"], key
    assert project["properties"]["author_name"]["minLength"] == 1


def test_requires_one_team_key_when_schema_exported() -> None:
    tracker = read_shipped_schema()["$defs"]["Tracker"]
    team = tracker["properties"]["team"]

    teams = tracker["properties"]["teams"]

    assert tracker["required"] == ["kind"]
    assert tracker["oneOf"] == [{"required": ["team"]}, {"required": ["teams"]}]
    assert teams["type"] == "array"
    assert teams["minItems"] == 1
    assert teams["items"]["pattern"] == team["pattern"]
    for node in (team, teams):
        assert "default" not in node
        assert "title" not in node
        assert "anyOf" not in node
    assert "tracker.teams" in team["description"]
    assert "tracker.team." in teams["description"]


CONVENTION_DESCRIPTIONS = {
    "branch": (
        "{prefix}, {ISSUE}, {issue_lower}, {slug}",
        "needs {ISSUE} or {issue_lower}",
        "Default {prefix}{issue_lower}-{slug}.",
    ),
    "commit_title": (
        "{ISSUE}, {type}, {scope}, {summary}",
        "needs {summary}",
        "Default {type}({scope}): {summary} ({ISSUE}).",
    ),
    "pr_title": (
        "{ISSUE}, {type}, {scope}, {summary}",
        "needs {summary}",
        "Default: the effective commit_title.",
    ),
}


def test_exports_optional_conventions_when_schema_exported() -> None:
    definitions = read_shipped_schema()["$defs"]
    conventions = definitions["Conventions"]

    for owner in ("Project", "Repo"):
        node = definitions[owner]["properties"]["conventions"]
        assert node["$ref"] == "#/$defs/Conventions", owner
        assert "conventions" not in definitions[owner]["required"], owner
        assert "anyOf" not in node, owner
        assert "default" not in node, owner
        assert "title" not in node, owner
    assert "repo" in definitions["Project"]["properties"]["conventions"]["description"]
    assert "project.conventions" in definitions["Repo"]["properties"]["conventions"]["description"]
    assert "required" not in conventions
    assert conventions["additionalProperties"] is False
    assert conventions["patternProperties"] == COMMENT_KEYS
    assert conventions["properties"].keys() == CONVENTION_DESCRIPTIONS.keys()
    for key, parts in CONVENTION_DESCRIPTIONS.items():
        node = conventions["properties"][key]
        assert node.keys() == {"type", "description"}, key
        assert node["type"] == "string", key
        for part in parts:
            assert part in node["description"], (key, part)


def test_exports_optional_platform_repository_when_schema_exported() -> None:
    platform = read_shipped_schema()["$defs"]["Platform"]

    assert platform["required"] == ["version"]
    assert platform["properties"]["repository"] == {
        "type": "string",
        "pattern": f"^{PLATFORM_REPOSITORY_PATTERN}$",
        "maxLength": 200,
        "description": "The platform's git source: the repository root as"
        " git+https://<host>/<path>, at most 200 characters. The hub runs"
        " <repository>@v<platform.version>#subdirectory=packages/agent-hub. Absent: the"
        " agent-hub release repository (docs/design/project-config.md).",
    }
