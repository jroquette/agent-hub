"""The JSON Schema of ``hub.json``: the model export and the copy shipped as package data.

The shipped ``hub.schema.json`` is regenerated with ``make hub-schema`` whenever ``HubConfig``
changes; a unit test fails while it differs from the export.
"""

import json

from agent_hub.core.hub_config.model import HubConfig

SCHEMA_PACKAGE = "agent_hub.core.hub_config"
SCHEMA_FILE = "hub.schema.json"


def export_schema_text() -> str:
    """The schema as the shipped file holds it: indented JSON, UTF-8 text, one final newline."""
    return json.dumps(HubConfig.model_json_schema(), indent=2, ensure_ascii=False) + "\n"
