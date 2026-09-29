"""The JSON byte form.

The one form of every JSON the platform writes: settings, manifests, ``hub.lock``.
Sorted keys, two-space indent, non-ASCII kept as UTF-8, one final newline: the same value always
gives the same bytes (spec Q-9).
"""

import json

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None


def dump_json(value: JsonValue) -> bytes:
    """Return ``value`` in the JSON byte form.

    Raises ``ValueError`` for a NaN or infinite float: ``json`` would write ``NaN``/``Infinity``,
    which is not JSON.
    """
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")
