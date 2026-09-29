"""The generator's JSON byte form, the one ``hub.lock`` uses (spec Q-9).

Sorted keys, two-space indent, non-ASCII kept as UTF-8, one final newline: the same value always
gives the same bytes. Every JSON file the generator builds in code goes through ``dump_json``.
"""

import json
from collections.abc import Callable

from agent_hub.core.hub_config.model import HubConfig

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None
type JsonBuilder = Callable[[HubConfig], JsonValue]
"""Builds a JSON file's value from the config; the registry names one per generator-built file."""


def dump_json(value: JsonValue) -> bytes:
    """Return ``value`` in the JSON byte form.

    Raises ``ValueError`` for a NaN or infinite float: ``json`` would write ``NaN``/``Infinity``,
    which is not JSON.
    """
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")
