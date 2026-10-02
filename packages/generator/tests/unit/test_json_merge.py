import json

import pytest

from agent_hub.core.hub_files.extension_inputs import REFUSED_KEYS
from agent_hub.core.json_form import dump_json
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.json_form import JsonValue
from agent_hub.generator.json_merge import MergeError, merge_json

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
SURROGATE = "not valid JSON here: a string holds a lone surrogate escape"


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
        (b'{"env": {"A": "\\ud800"}}', f"$: {SURROGATE}"),
        (b'{"\\ud800": 1}', f"$: {SURROGATE}"),
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
        "lone-surrogate-value",
        "lone-surrogate-key",
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


MARKETPLACE = ".claude-plugin/marketplace.project.json"
# Shaped like the managed marketplace (AGH-17 D4): the project's name and owner, then its plugins.
MANAGED_MARKETPLACE: JsonValue = {
    "name": "demo",
    "owner": {"name": "Demo Author", "email": "author@example.com"},
    "plugins": [
        {"name": "hub-workflow", "source": "./plugin/hub-workflow"},
        {"name": "demo", "source": "./plugin/demo"},
    ],
}
OWNED = "refused: the managed marketplace.json owns this"


def a_pin(name: str) -> JsonValue:
    return {"name": name, "source": {"source": "url", "url": f"https://example.com/{name}.git"}}


def test_appends_sibling_plugins_in_order_when_merged() -> None:
    # Q-1 (ADR 0009, no sort): the managed entries, then the sibling's in its own order.
    value = merged(
        MANAGED_MARKETPLACE, {"plugins": [a_pin("superpowers"), a_pin("aaa")]}, path=MARKETPLACE
    )

    assert isinstance(value, dict)
    assert value["plugins"] == [
        {"name": "hub-workflow", "source": "./plugin/hub-workflow"},
        {"name": "demo", "source": "./plugin/demo"},
        a_pin("superpowers"),
        a_pin("aaa"),
    ]


@pytest.mark.parametrize(
    ("plugins", "key_path"),
    [
        ([a_pin("hub-workflow")], "plugins[0].name"),
        ([a_pin("demo")], "plugins[0].name"),
        ([a_pin("superpowers"), {"name": "demo", "source": "./plugin/demo"}], "plugins[1].name"),
    ],
    ids=["base-plugin", "project-plugin", "same-as-managed-second"],
)
def test_refuses_sibling_entry_when_name_is_managed(
    plugins: list[JsonValue], key_path: str
) -> None:
    content = json.dumps({"plugins": plugins}).encode("utf-8")

    with pytest.raises(MergeError) as caught:
        merge_json(MANAGED_MARKETPLACE, content, path=MARKETPLACE)

    assert str(caught.value) == f"{MARKETPLACE}: {key_path}: {OWNED} entry"


@pytest.mark.parametrize(
    "project",
    [
        {"name": "other"},
        {"name": "demo"},
        {"owner": {"name": "Someone Else"}},
        {"owner": {}},
        {"description": "x", "owner": {"email": "x@example.com"}},
    ],
    ids=["name", "same-name", "owner", "empty-owner", "owner-after-description"],
)
def test_refuses_owned_key_when_sibling_sets_it(project: dict[str, JsonValue]) -> None:
    key = "name" if "name" in project else "owner"

    with pytest.raises(MergeError) as caught:
        merge_json(MANAGED_MARKETPLACE, json.dumps(project).encode("utf-8"), path=MARKETPLACE)

    assert str(caught.value) == f"{MARKETPLACE}: {key}: {OWNED} key"


def test_allows_description_and_metadata_when_sibling_sets_them() -> None:
    # Q-2: only `name` and `owner` are the managed part's; other top-level keys merge.
    project = {"description": "Our plugins.", "metadata": {"version": "1.0.0"}}

    assert merged(MANAGED_MARKETPLACE, project, path=MARKETPLACE) == {
        **MANAGED_MARKETPLACE,  # type: ignore[dict-item]
        "description": "Our plugins.",
        "metadata": {"version": "1.0.0"},
    }


def test_owns_names_only_for_marketplace_sibling_when_other_path_merged() -> None:
    # Another sibling may set `name`, `owner` and a `plugins` entry with a managed name.
    project = {"name": "x", "owner": {}, "plugins": [a_pin("demo")]}

    value = merged(MANAGED_MARKETPLACE, project, path="x.project.json")

    assert isinstance(value, dict)
    assert value["name"] == "x"
    assert value["plugins"] == [*MANAGED_MARKETPLACE["plugins"], a_pin("demo")]  # type: ignore[misc]
