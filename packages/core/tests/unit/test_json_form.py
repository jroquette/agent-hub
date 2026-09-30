import json

import pytest

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import InvalidJsonError, dump_json, load_json_bytes


def test_dumps_sorted_indented_utf8_when_value_given() -> None:
    value = {"name": "José", "active": True, "none": None}

    dumped = dump_json(value)

    # Keys sorted, two-space indent, ": " and "," separators, non-ASCII kept as UTF-8 bytes (not
    # ``\u`` escapes), one final newline.
    assert dumped == b'{\n  "active": true,\n  "name": "Jos\xc3\xa9",\n  "none": null\n}\n'
    assert json.loads(dumped) == value


def test_matches_lock_form_when_nested_value_dumped() -> None:
    # Shaped like hub.lock (docs/design/hub-sync.md § hub.lock): nested objects
    # and lists, keys given out of order at every level.
    value = {
        "platform_version": "0.1.0",
        "files": {"b.md": {"sha256": "f0", "kind": "generic"}, "a.md": {"sha256": "e1"}},
        "lock_version": 1,
        "modules": ["cloud", "bench"],
        "empty": {},
    }

    dumped = dump_json(value)

    assert dumped == (
        b"{\n"
        b'  "empty": {},\n'
        b'  "files": {\n'
        b'    "a.md": {\n'
        b'      "sha256": "e1"\n'
        b"    },\n"
        b'    "b.md": {\n'
        b'      "kind": "generic",\n'
        b'      "sha256": "f0"\n'
        b"    }\n"
        b"  },\n"
        b'  "lock_version": 1,\n'
        b'  "modules": [\n'
        b'    "cloud",\n'
        b'    "bench"\n'
        b"  ],\n"
        b'  "platform_version": "0.1.0"\n'
        b"}\n"
    )
    assert dumped == (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    assert dump_json({}) == b"{}\n"


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_rejects_value_when_number_not_finite(number: float) -> None:
    # ``json.dumps`` would write ``NaN``/``Infinity``: not JSON, yet ``json.loads`` reads it back.
    with pytest.raises(ValueError, match="not JSON compliant"):
        dump_json({"a": [number]})


TOO_MANY_DIGITS = (
    "not valid JSON here: a number has more than 4300 digits, which this reader does not accept"
)
TOO_DEEP = "not valid JSON here: it is nested too deeply"


def problem_of(content: bytes) -> str:
    with pytest.raises(InvalidJsonError) as caught:
        load_json_bytes(content)
    return caught.value.message


def test_loads_value_when_bytes_valid_json() -> None:
    content = '{"name": "José", "items": [1, 2.5, true, null]}'.encode()

    assert load_json_bytes(content) == {"name": "José", "items": [1, 2.5, True, None]}
    assert load_json_bytes(b"[]") == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"\xff\xfe{}", "not UTF-8 text: byte 0 cannot be decoded"),
        (b'{"a": "\xff"}', "not UTF-8 text: byte 7 cannot be decoded"),
        (
            b"\xef\xbb\xbf{}",
            "not valid JSON: the file starts with a UTF-8 byte order mark; save it without one",
        ),
        (b'{\n"a": }', "not valid JSON: Expecting value at line 2 column 6"),
        (
            b'{"a": 1,',
            "not valid JSON: Expecting property name enclosed in double quotes at line 1 column 9",
        ),
        (b"1" * 4301, TOO_MANY_DIGITS),
        (b'{"a": ' + b"1" * 4301 + b"}", TOO_MANY_DIGITS),
    ],
    ids=[
        "not-utf8",
        "not-utf8-inside-string",
        "byte-order-mark",
        "syntax-error",
        "unterminated",
        "long-integer",
        "nested-long-integer",
    ],
)
def test_names_problem_when_bytes_invalid(content: bytes, message: str) -> None:
    assert problem_of(content) == message


def test_names_problem_when_bytes_nested_deeply() -> None:
    # Whether this depth overflows depends on the C stack size, so the message is either the
    # nesting one or a syntax one; the nesting branch is pinned by the next test.
    message = problem_of(b"[" * 100_000)

    assert message == TOO_DEEP or message.startswith("not valid JSON: ")


def test_names_nesting_when_parser_recurses_too_deeply(monkeypatch: pytest.MonkeyPatch) -> None:
    def too_deep(*_: object, **__: object) -> object:
        raise RecursionError

    monkeypatch.setattr(json, "loads", too_deep)

    assert problem_of(b"{}") == TOO_DEEP


@pytest.mark.parametrize("newline", [b"\r\n", b"\r"], ids=["crlf", "bare-cr"])
def test_keeps_line_count_when_crlf_given(newline: bytes) -> None:
    # Decoded with universal newlines, as Path.read_text would: a CRLF or a bare CR ends one line.
    content = b"{" + newline + b'"a": 1,' + newline + b'"b": }'

    assert problem_of(content) == "not valid JSON: Expecting value at line 3 column 6"


def test_is_agent_hub_error_when_problem_raised() -> None:
    error = InvalidJsonError("not valid JSON here: it is nested too deeply")

    assert isinstance(error, AgentHubError)
    assert error.message == str(error) == TOO_DEEP


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b'{"a": 1, "a": 2}', 'not valid JSON here: the key "a" appears more than once'),
        (
            b'{"b": {"x\\n": 1, "x\\n": 2}}',
            'not valid JSON here: the key "x\\n" appears more than once',
        ),
        (b'{"a": NaN}', "not valid JSON here: NaN is not a JSON number"),
        (b"[Infinity]", "not valid JSON here: Infinity is not a JSON number"),
        (b"-Infinity", "not valid JSON here: -Infinity is not a JSON number"),
        (b'{"a": 1e999}', "not valid JSON here: a number is too large for this reader"),
        (
            b"\xef\xbb\xbf{}",
            "not valid JSON: the file starts with a UTF-8 byte order mark; save it without one",
        ),
    ],
    ids=[
        "duplicate-key",
        "nested-duplicate-key",
        "nan",
        "infinity",
        "minus-infinity",
        "overflow",
        "bom",
    ],
)
def test_refuses_duplicates_and_nan_when_strict(content: bytes, message: str) -> None:
    with pytest.raises(InvalidJsonError) as caught:
        load_json_bytes(content, strict=True)

    assert caught.value.message == message


def test_keeps_lenient_reading_when_not_strict() -> None:
    # The default is unchanged for hub.json and hub.lock: the last duplicate wins, NaN is read.
    assert load_json_bytes(b'{"a": 1, "a": 2}') == {"a": 2}
    assert load_json_bytes(b'{"a": 1, "a": 2}', strict=False) == {"a": 2}
    value = load_json_bytes(b"[NaN]")
    assert isinstance(value, list)
    assert value[0] != value[0]


SURROGATE = "not valid JSON here: a string holds a lone surrogate escape"


@pytest.mark.parametrize(
    "content",
    [
        b'{"env": {"A": "\\ud800"}}',
        b'{"\\ud800": 1}',
        b'["a", "x\\udfff"]',
        b'"\\udc00"',
        b'{"a": {"b\\ud800c": null}}',
    ],
    ids=["value", "key", "array-item", "top-level", "nested-key"],
)
def test_refuses_lone_surrogate_when_strict(content: bytes) -> None:
    # A lone surrogate has no UTF-8 form: the byte form could not write it back.
    with pytest.raises(InvalidJsonError) as caught:
        load_json_bytes(content, strict=True)

    assert caught.value.message == SURROGATE


def test_keeps_surrogate_pair_and_lenient_reading_when_surrogate_escaped() -> None:
    # A pair is one character; the default reader (hub.json, hub.lock) is unchanged.
    assert load_json_bytes(b'{"\\ud83d\\ude00": "\\ud83d\\ude00"}', strict=True) == {
        "\U0001f600": "\U0001f600"
    }
    assert load_json_bytes(b'{"\\ud800": ["\\udfff"]}') == {"\ud800": ["\udfff"]}


def test_loads_same_value_when_strict_and_input_clean() -> None:
    content = b'{"a": [1, 1.0, true, null, {"b": "c"}], "d": -0.5e3}'

    assert load_json_bytes(content, strict=True) == load_json_bytes(content)


BOM_MESSAGE = "not valid JSON: the file starts with a UTF-8 byte order mark; save it without one"


@pytest.mark.parametrize(
    ("content", "strict", "line", "message"),
    [
        (b'{\n"a": 1,\n"b": }', False, 3, "not valid JSON: Expecting value at line 3 column 6"),
        (b'{\r\n"a": 1,\r\n"b": }', False, 3, "not valid JSON: Expecting value at line 3 column 6"),
        (b"\xef\xbb\xbf{}", False, 1, BOM_MESSAGE),
        (b"\xef\xbb\xbf{}", True, 1, BOM_MESSAGE),
        (b"\xff\xfe{}", False, None, "not UTF-8 text: byte 0 cannot be decoded"),
        (b"1" * 4301, False, None, TOO_MANY_DIGITS),
        (
            b'{"a": 1,\n"a": 2}',
            True,
            None,
            'not valid JSON here: the key "a" appears more than once',
        ),
    ],
    ids=[
        "syntax-error",
        "syntax-error-crlf",
        "byte-order-mark",
        "byte-order-mark-strict",
        "not-utf8",
        "long-integer",
        "strict-duplicate-key",
    ],
)
def test_carries_line_when_json_invalid(
    content: bytes, *, strict: bool, line: int | None, message: str
) -> None:
    with pytest.raises(InvalidJsonError) as caught:
        load_json_bytes(content, strict=strict)

    assert caught.value.line == line
    assert caught.value.message == str(caught.value) == message


def test_carries_no_line_when_nested_too_deeply(monkeypatch: pytest.MonkeyPatch) -> None:
    def too_deep(*_: object, **__: object) -> object:
        raise RecursionError

    monkeypatch.setattr(json, "loads", too_deep)

    with pytest.raises(InvalidJsonError) as caught:
        load_json_bytes(b"{}")

    assert caught.value.line is None
    assert caught.value.message == TOO_DEEP


def test_carries_no_line_when_built_without_one() -> None:
    assert InvalidJsonError(TOO_DEEP).line is None
    assert InvalidJsonError(TOO_DEEP, line=4).line == 4
