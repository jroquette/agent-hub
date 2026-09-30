import json

import pytest

from agent_hub.core.json_form import dump_json
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.json_form import JsonValue
from agent_hub.generator.json_merge import REFUSED_KEYS, MergeError, merge_json

SETTINGS = ".claude/settings.project.json"
# Shaped like the managed settings: an object of objects and arrays, and a scalar.
TEMPLATE: JsonValue = {
    "includeCoAuthoredBy": False,
    "hooks": {"Stop": [{"hooks": [{"command": "stop", "type": "command"}]}]},
    "permissions": {"allow": ["Bash(git status)"], "deny": ["Read(.env)"]},
}


def merged(template: JsonValue, project: JsonValue | bytes, *, path: str = SETTINGS) -> JsonValue:
    content = project if isinstance(project, bytes) else json.dumps(project).encode("utf-8")
    value: JsonValue = json.loads(merge_json(template, content, path=path))
    return value


def test_merges_objects_by_key_when_both_objects() -> None:
    project = {"permissions": {"ask": ["Bash(rm *)"]}, "env": {"X": "1"}}

    assert merged(TEMPLATE, project) == {
        "includeCoAuthoredBy": False,
        "hooks": {"Stop": [{"hooks": [{"command": "stop", "type": "command"}]}]},
        "permissions": {
            "allow": ["Bash(git status)"],
            "ask": ["Bash(rm *)"],
            "deny": ["Read(.env)"],
        },
        "env": {"X": "1"},
    }


def test_keeps_project_scalar_when_both_scalars() -> None:
    template: JsonValue = {"a": False, "b": "template", "c": 1}

    # The project wins, whatever the scalar's type.
    assert merged(template, {"a": True, "b": 2, "c": "one"}) == {"a": True, "b": 2, "c": "one"}


def test_appends_project_items_after_template_when_arrays() -> None:
    project = {"permissions": {"allow": ["Bash(make *)", "Bash(uv run *)"]}}

    value = merged(TEMPLATE, project)

    assert isinstance(value, dict)
    assert value["permissions"] == {
        "allow": ["Bash(git status)", "Bash(make *)", "Bash(uv run *)"],
        "deny": ["Read(.env)"],
    }


def test_dedups_by_json_form_keeping_first_when_items_repeat() -> None:
    template: JsonValue = {"items": [1, True, {"a": 1, "b": [2]}, "x"]}
    # ``true`` and ``1``, ``1`` and ``1.0`` are different JSON values (Python ``==`` says equal);
    # an object is the same whatever its key order, and a repeat within the project is dropped.
    project = b'{"items": [1.0, 1, true, {"b": [2], "a": 1}, "y", "x", "y", false, 0]}'

    merged_bytes = merge_json(template, project, path=SETTINGS)

    assert merged_bytes == dump_json(
        {"items": [1, True, {"a": 1, "b": [2]}, "x", 1.0, "y", False, 0]}
    )


def test_dumps_one_form_when_merged() -> None:
    project = b'{"env":{"B":"2","A":"1"},  "permissions":{"allow":["Bash(make *)"]}}'

    merged_bytes = merge_json(TEMPLATE, project, path=SETTINGS)

    assert merged_bytes == dump_json(json.loads(merged_bytes))
    assert merged_bytes.endswith(b"}\n")


def test_returns_template_bytes_when_sibling_empty_object() -> None:
    assert merge_json(TEMPLATE, b"{}", path=SETTINGS) == dump_json(TEMPLATE)
    assert merge_json(TEMPLATE, b"{}\n", path=SETTINGS) == dump_json(TEMPLATE)


def test_merges_same_bytes_when_run_twice() -> None:
    project = b'{"permissions": {"allow": ["Bash(make *)"]}, "env": {"X": "1"}}'

    first = merge_json(TEMPLATE, project, path=SETTINGS)

    assert merge_json(TEMPLATE, project, path=SETTINGS) == first
    assert TEMPLATE == {
        "includeCoAuthoredBy": False,
        "hooks": {"Stop": [{"hooks": [{"command": "stop", "type": "command"}]}]},
        "permissions": {"allow": ["Bash(git status)"], "deny": ["Read(.env)"]},
    }


REFUSED = "refused: a project cannot set this key (it weakens the harness)"


@pytest.mark.parametrize(
    ("content", "line"),
    [
        (b'{"a": }', "$: not valid JSON: Expecting value at line 1 column 7"),
        (b'{"a": "\xff"}', "$: not UTF-8 text: byte 7 cannot be decoded"),
        (
            b"\xef\xbb\xbf{}",
            "$: not valid JSON: the file starts with a UTF-8 byte order mark; save it without one",
        ),
        (b'{"a": 1, "a": 2}', '$: not valid JSON here: the key "a" appears more than once'),
        (b'{"a": NaN}', "$: not valid JSON here: NaN is not a JSON number"),
        (b"[]", "$: an array where the template has an object"),
        (
            b'{"permissions": {"allow": "x"}}',
            "permissions.allow: a string where the template has an array",
        ),
        (b'{"hooks": []}', "hooks: an array where the template has an object"),
        (
            b'{"includeCoAuthoredBy": {}}',
            "includeCoAuthoredBy: an object where the template has a boolean",
        ),
        (b'{"env": {"A": null}}', "env.A: null is refused: the merge never deletes a key"),
        (
            b'{"permissions": {"allow": ["x", null]}}',
            "permissions.allow[1]: null is refused: the merge never deletes a key",
        ),
        (
            b'{"includeCoAuthoredBy": null}',
            "includeCoAuthoredBy: null is refused: the merge never deletes a key",
        ),
        (b'{"disableAllHooks": false}', f"disableAllHooks: {REFUSED}"),
        (b'{"permissions": {"defaultMode": "plan"}}', f"permissions.defaultMode: {REFUSED}"),
        (b'{"a b": {"c": null}}', '["a b"].c: null is refused: the merge never deletes a key'),
    ],
    ids=[
        "invalid-json",
        "not-utf8",
        "byte-order-mark",
        "duplicate-key",
        "nan",
        "top-level-array",
        "scalar-for-array",
        "array-for-object",
        "object-for-scalar",
        "null-in-new-object",
        "null-in-array",
        "null-for-scalar",
        "disable-all-hooks",
        "default-mode",
        "quoted-key",
    ],
)
def test_refuses_sibling_when_malformed_or_weakening(content: bytes, line: str) -> None:
    with pytest.raises(MergeError) as caught:
        merge_json(TEMPLATE, content, path=SETTINGS)

    assert str(caught.value) == f"{SETTINGS}: {line}"
    assert isinstance(caught.value, GeneratorError)
    assert "\n" not in str(caught.value)


def test_refuses_keys_only_for_their_sibling_when_other_path_merged() -> None:
    # Weakening keys belong to the settings sibling; another sibling may hold these names.
    assert merged({}, {"disableAllHooks": False}, path="x.project.json") == {
        "disableAllHooks": False
    }
    assert set(REFUSED_KEYS) == {SETTINGS}


def test_refuses_sibling_when_nested_too_deeply_to_merge() -> None:
    # Parsed, but deeper than the merge and the byte form can walk: one line, no traceback.
    content = b'{"env": ' + b"[" * 5000 + b"]" * 5000 + b"}"

    with pytest.raises(MergeError) as caught:
        merge_json(TEMPLATE, content, path=SETTINGS)

    assert str(caught.value) == f"{SETTINGS}: $: not valid JSON here: it is nested too deeply"
