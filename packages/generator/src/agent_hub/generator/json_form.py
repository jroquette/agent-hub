"""The generator's view of the JSON byte form, which lives in core (``agent_hub.core.json_form``).

Core owns ``dump_json`` so ``hub.lock`` and the generator's JSON files share one form. This module
re-exports it and adds ``JsonBuilder``. Every JSON file the generator builds in code goes through
``dump_json``.
"""

from collections.abc import Callable

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.json_form import JsonValue, dump_json

__all__ = ["JsonBuilder", "JsonValue", "dump_json"]

type JsonBuilder = Callable[[HubConfig], JsonValue]
"""Builds a JSON file's value from the config; the registry names one per generator-built file."""
