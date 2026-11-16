"""The JSON Schemas core ships as package data, read back for the drift tests.

``make hub-schema`` and ``make output-schemas`` write them from the models; the tests compare
what ships with a fresh export. A hub reads its copies from the rendered files, never from
here.
"""

import json
from importlib.resources import files
from typing import Any

from agent_hub.core.features.agent_outputs import (
    OUTPUT_SCHEMA_FILES,
    OUTPUT_SCHEMA_PACKAGE,
    OutputSchema,
)
from agent_hub.core.hub_config.schema import SCHEMA_FILE, SCHEMA_PACKAGE


def read_shipped_schema() -> dict[str, Any]:
    """The ``hub.json`` schema shipped with the package, read as package data."""
    text = files(SCHEMA_PACKAGE).joinpath(SCHEMA_FILE).read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def read_shipped_output_schema(kind: OutputSchema) -> dict[str, Any]:
    """The JSON Schema of one output shipped with the package, read as package data."""
    package_file = files(OUTPUT_SCHEMA_PACKAGE).joinpath(OUTPUT_SCHEMA_FILES[kind])
    schema: dict[str, Any] = json.loads(package_file.read_text(encoding="utf-8"))
    return schema
