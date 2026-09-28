import json
from collections.abc import Iterator
from typing import Any

from agent_hub.core.hub_config.model import HubConfig
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
    assert max_lines["propertyNames"] == {"minLength": 1}
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
