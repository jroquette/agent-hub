"""The JSON byte form, and the one parser of the JSON files a hub holds.

The one form of every JSON the platform writes: settings, manifests, ``hub.lock``.
Sorted keys, two-space indent, non-ASCII kept as UTF-8, one final newline: the same value always
gives the same bytes (spec Q-9).

``load_json_bytes`` reads ``hub.json`` and ``hub.lock`` back: each problem is one message, the
same for every file, which the caller prefixes with the file's name. Its strict mode, for the
seeded ``*.project.json`` siblings (spec Q-18), also refuses what ``json`` accepts but is not one
JSON value: a repeated key, ``NaN``/``Infinity``, a number too large for a float and a lone
surrogate escape in a string or key.
"""

import io
import json
import math

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_config.versions import cut_echo

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None

# Written as an escape: the character itself is invisible in the source.
BYTE_ORDER_MARK = "\N{ZERO WIDTH NO-BREAK SPACE}"


class InvalidJsonError(AgentHubError):
    """Bytes that are not a JSON value this platform reads; ``message`` says why, on one line.

    ``line`` is the line the parser stopped at for a syntax error, 1 for a byte order mark, and
    ``None`` for every other problem (not UTF-8, too many digits, too deep, a strict refusal).
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        self.message = message
        self.line = line
        super().__init__(message)


def dump_json(value: JsonValue) -> bytes:
    """Return ``value`` in the JSON byte form.

    Raises ``ValueError`` for a NaN or infinite float: ``json`` would write ``NaN``/``Infinity``,
    which is not JSON.
    """
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def load_json_bytes(content: bytes, *, strict: bool = False) -> JsonValue:
    """Return the JSON value ``content`` holds.

    Raises ``InvalidJsonError`` when the bytes are not UTF-8, start with a byte order mark, are not
    JSON, hold a number of more than 4300 digits or are nested too deeply. With ``strict``, also
    when an object repeats a key (never "last one wins"), or a number is ``NaN``, ``Infinity``,
    ``-Infinity`` or too large for a float, or a string or key holds a lone surrogate escape
    (``\\ud800``: no UTF-8 form).
    """
    return _parse(_decode(content), strict=strict)


def _decode(content: bytes) -> str:
    # Decoded as Path.read_text would: strict UTF-8 with universal newlines, so the line and
    # column in a JSON message count as before, while the caller keeps the bytes unchanged.
    try:
        return io.TextIOWrapper(io.BytesIO(content), encoding="utf-8").read()
    except UnicodeDecodeError as error:
        message = f"not UTF-8 text: byte {error.start} cannot be decoded"
        raise InvalidJsonError(message) from None


def _parse(text: str, *, strict: bool) -> JsonValue:
    if text.startswith(BYTE_ORDER_MARK):
        raise InvalidJsonError(
            "not valid JSON: the file starts with a UTF-8 byte order mark; save it without one",
            line=1,
        )
    try:
        value: JsonValue = _load_strict(text) if strict else json.loads(text)
    except json.JSONDecodeError as error:
        message = f"not valid JSON: {error.msg} at line {error.lineno} column {error.colno}"
        raise InvalidJsonError(message, line=error.lineno) from None
    except _StrictError as error:
        raise InvalidJsonError(f"not valid JSON here: {error.reason}") from None
    except ValueError:
        # Python reads integers of at most 4300 digits (sys.get_int_max_str_digits()).
        raise InvalidJsonError(
            "not valid JSON here: a number has more than 4300 digits,"
            " which this reader does not accept"
        ) from None
    except RecursionError:
        raise InvalidJsonError("not valid JSON here: it is nested too deeply") from None
    return value


class _StrictError(Exception):
    """Raised inside ``json.loads`` by the strict hooks; ``reason`` completes the message."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _load_strict(text: str) -> JsonValue:
    value: JsonValue = json.loads(
        text,
        object_pairs_hook=_unique_keys,
        parse_constant=_refuse_constant,
        parse_float=_finite_float,
    )
    _refuse_lone_surrogates(value)
    return value


def _refuse_lone_surrogates(value: JsonValue) -> None:
    # A ``\ud800`` escape parses to a lone surrogate, which has no UTF-8 form: the byte form
    # could not write it back. Walked with a stack: a value nested deeper than the recursion limit
    # still gets the merge's one-line message.
    pending: list[JsonValue] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and not _is_utf8(item):
            raise _StrictError("a string holds a lone surrogate escape")


def _is_utf8(text: str) -> bool:
    # Only a lone surrogate has no UTF-8 form.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _unique_keys(pairs: list[tuple[str, JsonValue]]) -> JsonValue:
    value: dict[str, JsonValue] = {}
    for key, item in pairs:
        if key in value:
            # Written as a JSON string: a key holding a line break stays on one line; cut, so a
            # huge key gives a message of bounded length.
            raise _StrictError(f"the key {cut_echo(json.dumps(key))} appears more than once")
        value[key] = item
    return value


def _refuse_constant(name: str) -> JsonValue:
    raise _StrictError(f"{name} is not a JSON number")


def _finite_float(text: str) -> JsonValue:
    number = float(text)
    if math.isinf(number):
        raise _StrictError("a number is too large for this reader")
    return number
