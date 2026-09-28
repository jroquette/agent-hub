"""The JSON Schema of ``hub.json``: the model export and the copy shipped as package data.

The shipped ``hub.schema.json`` is regenerated with ``make hub-schema`` whenever ``HubConfig``
changes; a unit test fails while it differs from the export.
"""

import json
from importlib.resources import files
from typing import Any

from agent_hub.core.hub_config.model import HubConfig

SCHEMA_PACKAGE = "agent_hub.core.hub_config"
SCHEMA_FILE = "hub.schema.json"


def export_schema_text() -> str:
    """The schema as the shipped file holds it: indented JSON, UTF-8 text, one final newline."""
    return json.dumps(HubConfig.model_json_schema(), indent=2, ensure_ascii=False) + "\n"


def read_shipped_schema() -> dict[str, Any]:
    """The schema shipped with the package, read as package data."""
    text = files(SCHEMA_PACKAGE).joinpath(SCHEMA_FILE).read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema
