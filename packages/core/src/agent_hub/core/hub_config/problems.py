"""Problems in a ``hub.json``, each at a JSON path, as the CLI and ``hub doctor`` print them."""

import json
import re
from collections.abc import Sequence
from typing import NamedTuple

ROOT_PATH = "$"
# A config file whose top level is not an object: hub.json and hub.local.json say it alike.
NOT_AN_OBJECT_MESSAGE = "must be a JSON object"
# A key written as is after a dot; any other key is quoted, so the path cannot be misread.
_PLAIN_KEY = re.compile(r"[A-Za-z_$][A-Za-z0-9_$-]*")


class ConfigProblem(NamedTuple):
    """One problem in the file: where it is, and what is wrong."""

    path: str
    message: str


def json_path(loc: Sequence[str | int]) -> str:
    """The JSON path of a location: ``repos[0].dir``, ``doctor.rules["bench.tasks"]``, ``$``.

    A key that is not a plain name is written as a JSON string, escaped, so a key holding a
    dot, a quote or a line break still reads as one key on one line.
    """
    path = ""
    for segment in loc:
        if isinstance(segment, int):
            path += f"[{segment}]"
        elif _PLAIN_KEY.fullmatch(segment):
            path += f".{segment}" if path else segment
        else:
            path += f"[{json.dumps(segment)}]"
    return path or ROOT_PATH


def json_type(value: object) -> str:
    """The JSON type of a parsed value, as a message names it: ``a string``, ``null``, …

    A message about a value of the wrong type names this, never the value, which may be a
    secret pasted in the wrong place.
    """
    # ``bool`` first: it is an ``int`` subclass.
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, int | float):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "an array"
    if isinstance(value, dict):
        return "an object"
    if value is None:
        return "null"
    msg = f"not a parsed JSON value: {type(value).__name__}"
    raise TypeError(msg)


def one_line(text: str) -> str:
    """The text with every character that is not printable escaped, line breaks included."""
    return "".join(char if char.isprintable() else ascii(char)[1:-1] for char in text)
