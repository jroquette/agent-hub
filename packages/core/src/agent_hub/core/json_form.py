"""The JSON byte form, and the one parser of the JSON files a hub holds.

The one form of every JSON the platform writes: settings, manifests, ``hub.lock``.
Sorted keys, two-space indent, non-ASCII kept as UTF-8, one final newline: the same value always
gives the same bytes (spec Q-9).

``load_json_bytes`` reads ``hub.json`` and ``hub.lock`` back: each problem is one message, the
same for every file, which the caller prefixes with the file's name.
"""

import io
import json

from agent_hub.core.errors import AgentHubError

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None

# Written as an escape: the character itself is invisible in the source.
BYTE_ORDER_MARK = "\N{ZERO WIDTH NO-BREAK SPACE}"


class InvalidJsonError(AgentHubError):
    """Bytes that are not a JSON value this platform reads; ``message`` says why, on one line."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def dump_json(value: JsonValue) -> bytes:
    """Return ``value`` in the JSON byte form.

    Raises ``ValueError`` for a NaN or infinite float: ``json`` would write ``NaN``/``Infinity``,
    which is not JSON.
    """
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def load_json_bytes(content: bytes) -> JsonValue:
    """Return the JSON value ``content`` holds.

    Raises ``InvalidJsonError`` when the bytes are not UTF-8, start with a byte order mark, are not
    JSON, hold a number of more than 4300 digits or are nested too deeply.
    """
    return _parse(_decode(content))


def _decode(content: bytes) -> str:
    # Decoded as Path.read_text would: strict UTF-8 with universal newlines, so the line and
    # column in a JSON message count as before, while the caller keeps the bytes unchanged.
    try:
        return io.TextIOWrapper(io.BytesIO(content), encoding="utf-8").read()
    except UnicodeDecodeError as error:
        message = f"not UTF-8 text: byte {error.start} cannot be decoded"
        raise InvalidJsonError(message) from None


def _parse(text: str) -> JsonValue:
    if text.startswith(BYTE_ORDER_MARK):
        raise InvalidJsonError(
            "not valid JSON: the file starts with a UTF-8 byte order mark; save it without one"
        )
    try:
        value: JsonValue = json.loads(text)
    except json.JSONDecodeError as error:
        message = f"not valid JSON: {error.msg} at line {error.lineno} column {error.colno}"
        raise InvalidJsonError(message) from None
    except ValueError:
        # Python reads integers of at most 4300 digits (sys.get_int_max_str_digits()).
        raise InvalidJsonError(
            "not valid JSON here: a number has more than 4300 digits,"
            " which this reader does not accept"
        ) from None
    except RecursionError:
        raise InvalidJsonError("not valid JSON here: it is nested too deeply") from None
    return value
