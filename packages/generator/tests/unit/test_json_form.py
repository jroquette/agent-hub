import json

import pytest

from agent_hub.generator.json_form import dump_json


def test_dumps_sorted_indented_utf8_when_value_given() -> None:
    value = {"name": "José", "active": True, "none": None}

    dumped = dump_json(value)

    # Keys sorted, two-space indent, ": " and "," separators, non-ASCII kept as UTF-8 bytes (not
    # ``\u`` escapes), one final newline.
    assert dumped == b'{\n  "active": true,\n  "name": "Jos\xc3\xa9",\n  "none": null\n}\n'
    assert json.loads(dumped) == value


def test_matches_lock_form_when_nested_value_dumped() -> None:
    # Shaped like hub.lock (docs/design/hub-generator.md § hub.lock and hub sync): nested objects
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
