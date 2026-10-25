"""Strict workflow loader (AC-213.2): YAML through a refusing SafeLoader, JSON through core's
strict reader; each key path's line recorded for the document model's errors (AC-213.1)."""

import json
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_hub.core.hub_config.versions import ECHO_LIMIT
from agent_hub.core.json_form import JsonValue
from agent_hub.generator.scenario_yaml import render_document
from agent_hub.generator.workflow_yaml import (
    MAX_LINE_DEPTH,
    MAX_LINE_ENTRIES,
    MAX_WORKFLOW_BYTES,
    WorkflowFileError,
    load_workflow_bytes,
)

_PACKAGES = Path(__file__).parents[3]
TREES = _PACKAGES / "core" / "tests" / "data" / "scenarios" / "blocks" / "tree"
# The web's copy of what the API gives as a tree scenario's ``document`` (this loader's parse),
# which the builder's round trip is checked against (AC-507.24).
WEB_TREES = _PACKAGES.parent / "apps" / "web" / "src" / "testing" / "treeDocuments.ts"
UPDATE_VARIABLE = "GOLDEN_UPDATE"
WEB_TREES_HINT = (
    f"Update: {UPDATE_VARIABLE}=1 uv run --locked --all-packages pytest "
    "packages/generator/tests/unit/test_workflow_yaml.py -q, then review and commit the diff"
)
WEB_TREES_HEADER = """\
// Generated: the strict loader's parse of each scenario of
// packages/core/tests/data/scenarios/blocks/tree, as GET /api/v1/scenarios/{project}/{name}
// gives it as `document`, and the scenario writer's key order. test_workflow_yaml.py
// (packages/generator/tests/unit) checks it and rewrites it with GOLDEN_UPDATE=1. Tests read
// it through aTreeDocument and anEveryKeyTree (builders.ts).
"""
# A synthetic tree holding every key the scenario writer orders. The web's module holds it as
# the writer writes it from its keys in reverse order, read back: the builder writes a file in
# the writer's key order, which its round trip of this document checks.
EVERY_KEY: JsonValue = {
    "version": 2,
    "kind": "scenario",
    "name": "every-key",
    "revision": 3,
    "description": "Every step key of the tree format",
    "inputs": {"order_id": {"required": True}},
    "stages": [
        {
            "name": "Every key",
            "description": "Each step with its optional keys",
            "steps": [
                {
                    "do": "order-get",
                    "id": "get-order",
                    "description": "Reads the order",
                    "with": {"order_id": "$INPUTS.order_id"},
                    "timeout": "5m",
                    "capture": {"status": "$self.output.status"},
                    "retry": {"max_attempts": 3, "delay": "5s", "on_error": "all"},
                },
                {
                    "wait_until": "order-state",
                    "until": "$self.output.status == 'DONE'",
                    "every": "15s",
                    "timeout": "10m",
                    "retry": {"max_attempts": 1},
                },
                {
                    "you": "Approve the order, or reject it.",
                    "description": "A person decides",
                    "decisions": [
                        {"id": "approve", "label": "Approve"},
                        {"id": "reject", "label": "Reject"},
                    ],
                    "capture_response": True,
                },
                {"wait": {"duration": "1m", "until": "2030-01-01T00:00:00Z"}},
                {
                    "wait": {
                        "attention": "Pick a carrier",
                        "options": [
                            {"id": "fast", "label": "Fast"},
                            {"id": "slow", "label": "Slow"},
                        ],
                    },
                    "id": "pick-carrier",
                    "description": "Waits for a choice",
                },
                {
                    "include": "blocks-repeat",
                    "description": "Polls the review",
                    "with": {"shop_order_id": "$INPUTS.order_id"},
                },
                {
                    "if": "$CTX.status == 'DONE'",
                    "description": "Only when done",
                    "then": [{"wait": {"duration": "1m"}}],
                    "else": [{"do": "order-d"}],
                },
                {
                    "together": [[{"do": "order-a"}], [{"do": "order-b"}]],
                    "description": "Both at once",
                },
                {
                    "repeat": {
                        "max": 3,
                        "until": "$get-order.output.status == 'DONE'",
                        "steps": [{"do": "order-c"}],
                    },
                    "id": "again",
                    "description": "Tries again",
                },
            ],
        }
    ],
}


def _refusal(content: bytes, source: str = "workflows/p/w.yaml") -> WorkflowFileError:
    with pytest.raises(WorkflowFileError) as caught:
        load_workflow_bytes(content, source=source)
    return caught.value


def test_returns_mapping_when_yaml_is_plain() -> None:
    content = (
        b"version: 1\nname: w\nnodes:\n  - id: a\n    type: shell\n    command: [make, check]\n"
    )

    document = load_workflow_bytes(content, source="w.yaml").document

    assert document == {
        "version": 1,
        "name": "w",
        "nodes": [{"id": "a", "type": "shell", "command": ["make", "check"]}],
    }


def test_refuses_with_line_when_key_repeats() -> None:
    error = _refusal(b"name: w\nversion: 1\nname: x\n")

    assert error.line == 3
    assert "name" in error.reason
    assert "more than once" in error.reason


def test_refuses_with_line_when_nested_key_repeats() -> None:
    error = _refusal(b"nodes:\n  - id: a\n    type: shell\n    id: b\n")

    assert error.line == 4


def test_refuses_with_line_when_anchor_used() -> None:
    error = _refusal(b"name: w\nschema: &shared {type: object}\n")

    assert error.line == 2
    assert "anchor" in error.reason


def test_refuses_with_line_when_alias_used() -> None:
    error = _refusal(b"name: w\nschema: *shared\n")

    assert error.line == 2
    assert "alias" in error.reason


@pytest.mark.parametrize(
    "content",
    [b"name: !!str w\n", b"name: !custom w\n", b"name: ! w\n", b"nodes: !!seq []\n"],
)
def test_refuses_with_line_when_tag_used(content: bytes) -> None:
    error = _refusal(content)

    assert error.line == 1
    assert "tag" in error.reason


def test_refuses_when_tag_directive_given() -> None:
    error = _refusal(b"%TAG ! tag:example.com,2026:\n---\nname: w\n")

    assert "tag" in error.reason


def test_refuses_with_line_when_second_document_follows() -> None:
    error = _refusal(b"name: w\n---\nname: x\n")

    assert error.line == 2
    assert "one document" in error.reason


def test_refuses_without_line_when_over_byte_cap() -> None:
    content = b"name: w\n" + b"#" * MAX_WORKFLOW_BYTES + b"\n"

    error = _refusal(content)

    assert error.line is None
    assert str(MAX_WORKFLOW_BYTES) in error.reason


def test_accepts_document_when_exactly_at_byte_cap() -> None:
    head = b"name: w\n#"
    content = head + b"x" * (MAX_WORKFLOW_BYTES - len(head) - 1) + b"\n"

    assert load_workflow_bytes(content, source="w.yaml").document == {"name": "w"}


def test_reports_file_and_line_when_syntax_is_broken() -> None:
    error = _refusal(b"name: w\nnodes: [a, b\n", source="workflows/p/w.yaml")

    assert error.source == "workflows/p/w.yaml"
    assert error.line is not None
    assert str(error).startswith(f"workflows/p/w.yaml:{error.line}: ")


@pytest.mark.parametrize("content", [b"", b"# only a comment\n", b"---\n"])
def test_refuses_when_document_is_empty(content: bytes) -> None:
    assert "mapping" in _refusal(content).reason


def test_refuses_when_top_level_is_not_mapping() -> None:
    error = _refusal(b"- a\n- b\n")

    assert error.line == 1
    assert "mapping" in error.reason


@pytest.mark.parametrize("content", [b"1: a\n", b"true: a\n", b"~: a\n", b"? [a]\n: b\n"])
def test_refuses_with_line_when_key_is_not_string(content: bytes) -> None:
    error = _refusal(content)

    assert error.line == 1
    assert "key" in error.reason


def test_reads_scalars_as_json_values_when_yaml_one_one_forms_given() -> None:
    content = (
        b"on: yes\nno_: off\nday: 2026-10-14\nlegacy_octal: 012\nhex: 0x1f\n"
        b"time: 1:30\ninf: .inf\nflag: True\nnothing: null\nempty:\nratio: -1.5e3\nn: -7\n"
    )

    assert load_workflow_bytes(content, source="w.yaml").document == {
        "on": "yes",
        "no_": "off",
        "day": "2026-10-14",
        "legacy_octal": "012",
        "hex": "0x1f",
        "time": "1:30",
        "inf": ".inf",
        "flag": True,
        "nothing": None,
        "empty": None,
        "ratio": -1500.0,
        "n": -7,
    }


def test_keeps_text_when_merge_key_given() -> None:
    assert load_workflow_bytes(b"<<: {a: 1}\n", source="w.yaml").document == {"<<": {"a": 1}}


def test_refuses_when_bytes_are_not_utf8() -> None:
    error = _refusal(b"name: \xff\n")

    assert error.line is None
    assert "UTF-8" in error.reason


def test_refuses_when_nested_too_deeply() -> None:
    assert "deep" in _refusal(b"a: " + b"[" * 20_000 + b"]" * 20_000 + b"\n").reason


def test_returns_mapping_when_json_given() -> None:
    content = b'{"version": 1, "name": "w", "nodes": [{"id": "a", "type": "halt"}]}'

    document = load_workflow_bytes(content, source="workflows/p/w.json").document

    assert document == {"version": 1, "name": "w", "nodes": [{"id": "a", "type": "halt"}]}


def test_refuses_when_json_repeats_key() -> None:
    error = _refusal(b'{"name": "w", "name": "x"}', source="w.json")

    assert "more than once" in error.reason


def test_reports_line_when_json_is_broken() -> None:
    error = _refusal(b'{\n"name": "w",\n"version" 1}', source="w.json")

    assert error.line == 3


def test_refuses_when_json_top_level_is_not_object() -> None:
    assert "mapping" in _refusal(b"[1, 2]", source="w.json").reason


def test_refuses_without_line_when_json_over_byte_cap() -> None:
    content = b'{"a": "' + b"x" * MAX_WORKFLOW_BYTES + b'"}'

    assert _refusal(content, source="w.json").line is None


@pytest.mark.parametrize(("content", "line"), [(b"a: \x00b\n", 1), (b"name: w\nb: \x01\n", 2)])
def test_refuses_with_line_when_control_character_given(content: bytes, line: int) -> None:
    error = _refusal(content)

    assert error.line == line
    assert "character" in error.reason


@pytest.mark.parametrize(
    ("content", "line"), [(b'a: "\\ud800"\n', 1), (b'name: w\n"\\udc00": 1\n', 2)]
)
def test_refuses_with_line_when_surrogate_escape_given(content: bytes, line: int) -> None:
    error = _refusal(content)

    assert error.line == line
    assert "surrogate" in error.reason


def test_cuts_echoed_parser_text_when_reason_is_long() -> None:
    handle = b"!" + b"h" * 5_000 + b"!"
    error = _refusal(b"a: " + handle + b"x\n")

    assert error.line == 1
    assert "hhhh" in error.reason
    assert error.reason.endswith("…")
    assert len(error.reason) <= len("not valid YAML: ") + ECHO_LIMIT


@pytest.mark.parametrize("text", ["012", "-01", "01.5", ".5", "1.", "+007"])
def test_keeps_text_when_digits_are_not_json_numbers(text: str) -> None:
    content = f"v: {text}\n".encode()

    assert load_workflow_bytes(content, source="w.yaml").document == {"v": text}


def test_records_line_of_each_key_and_item_when_yaml_loaded() -> None:
    content = (
        b"# a workflow\n"
        b"version: 1\n"
        b"nodes:\n"
        b"  - id: a\n"
        b"    command:\n"
        b"      - make\n"
        b"      - check\n"
        b"  - {id: b, type: halt}\n"
    )

    lines = load_workflow_bytes(content, source="w.yaml").lines

    assert dict(lines) == {
        (): 2,
        ("version",): 2,
        ("nodes",): 3,
        ("nodes", 0): 4,
        ("nodes", 0, "id"): 4,
        ("nodes", 0, "command"): 5,
        ("nodes", 0, "command", 0): 6,
        ("nodes", 0, "command", 1): 7,
        ("nodes", 1): 8,
        ("nodes", 1, "id"): 8,
        ("nodes", 1, "type"): 8,
    }


def test_records_line_of_each_key_when_json_loaded() -> None:
    content = b'{\n  "version": 1,\n  "nodes": [\n    {"id": "a"}\n  ]\n}\n'

    lines = load_workflow_bytes(content, source="w.json").lines

    assert dict(lines) == {
        (): 1,
        ("version",): 2,
        ("nodes",): 3,
        ("nodes", 0): 4,
        ("nodes", 0, "id"): 4,
    }


def _nested(depth: int, items: int) -> bytes:
    """``a: {a: … [items] }`` nested ``depth`` mappings deep, in flow style."""
    leaf = "[" + ", ".join(str(n) for n in range(items)) + "]"
    return ("a: " + "{a: " * (depth - 1) + leaf + "}" * (depth - 1) + "\n").encode()


def test_bounds_key_lines_when_document_is_deep_and_wide() -> None:
    lines = load_workflow_bytes(_nested(50, 1_000), source="w.yaml").lines

    assert len(lines) <= MAX_LINE_ENTRIES
    assert all(len(path) <= MAX_LINE_DEPTH for path in lines)
    assert ("a",) * MAX_LINE_DEPTH in lines


def test_keeps_shallow_lines_first_when_entry_cap_reached() -> None:
    content = b"version: 1\nitems:\n" + b"  - 1\n" * (MAX_LINE_ENTRIES + 500) + b"tail: 2\n"

    lines = load_workflow_bytes(content, source="w.yaml").lines

    assert len(lines) == MAX_LINE_ENTRIES
    assert lines[("tail",)] == MAX_LINE_ENTRIES + 503
    assert lines[("items", 0)] == 3


def test_records_lines_when_json_is_tab_indented() -> None:
    content = b'{\n\t"version": 1,\n\t"nodes": [\n\t\t{"id": "a"}\n\t]\n}\n'

    lines = load_workflow_bytes(content, source="w.json").lines

    assert dict(lines) == {
        (): 1,
        ("version",): 2,
        ("nodes",): 3,
        ("nodes", 0): 4,
        ("nodes", 0, "id"): 4,
    }


@pytest.mark.parametrize("odd", ["\x7f", "\x85", "\u2028", "\u2029"])
def test_leaves_lines_empty_when_json_text_defeats_composer(odd: str) -> None:
    content = f'{{\n"a": "x{odd}y",\n"b": 1\n}}\n'.encode()

    loaded = load_workflow_bytes(content, source="w.json")

    assert loaded.document == {"a": f"x{odd}y", "b": 1}
    assert dict(loaded.lines) == {}


@pytest.mark.parametrize(
    ("content", "line"),
    [(b"a: 1\r\nb: 2\rc: \x00\n", 3), (b"a: 1\r\n\r\nb: \x01\n", 3), (b"a: \xc2\x85b: \x00\n", 2)],
)
def test_counts_breaks_as_marks_do_when_control_character_given(content: bytes, line: int) -> None:
    assert _refusal(content).line == line


def web_tree_module(documents: Mapping[str, object], every_key: object) -> str:
    """The web's module of ``documents`` by scenario name and the writer's ``every_key``, as the
    check writes it."""
    body = json.dumps(dict(sorted(documents.items())), indent=2, ensure_ascii=False)
    declared = "export const TREE_DOCUMENTS: Readonly<Record<string, unknown>> ="
    ordered = json.dumps(every_key, indent=2, ensure_ascii=False)
    written = (
        "// The scenario writer's key order: a tree holding every key it orders, written from its\n"
        "// keys in reverse order and read back.\n"
        "export const EVERY_KEY_DOCUMENT: Readonly<Record<string, unknown>> ="
    )
    return f"{WEB_TREES_HEADER}{declared} {body};\n\n{written} {ordered};\n"


def reversed_keys(value: JsonValue) -> JsonValue:
    """``value`` with the keys of each mapping in it in reverse order."""
    if isinstance(value, dict):
        return {key: reversed_keys(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [reversed_keys(item) for item in value]
    return value


def update_mode() -> bool:
    """Whether ``GOLDEN_UPDATE=1`` asks to rewrite the web's module; fails when ``CI`` is set."""
    if os.environ.get(UPDATE_VARIABLE) != "1":
        return False
    if os.environ.get("CI"):
        pytest.fail(
            f"{UPDATE_VARIABLE}=1 is refused when CI is set: goldens are regenerated locally, "
            "reviewed and committed"
        )
    return True


def test_refuses_to_rewrite_web_tree_documents_when_ci_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UPDATE_VARIABLE, "1")
    monkeypatch.setenv("CI", "true")

    with pytest.raises(pytest.fail.Exception, match="GOLDEN_UPDATE=1 is refused when CI is set"):
        update_mode()


def test_holds_the_loaders_parse_when_web_tree_documents_read() -> None:
    documents = {
        path.stem: load_workflow_bytes(path.read_bytes(), source=path.name).document
        for path in sorted(TREES.glob("*.yaml"))
    }
    scrambled = reversed_keys(EVERY_KEY)
    assert isinstance(scrambled, dict)
    text = render_document(scrambled)
    every_key = load_workflow_bytes(text.encode(), source="every-key.yaml").document
    expected = web_tree_module(documents, every_key)
    if update_mode():
        WEB_TREES.write_text(expected, encoding="utf-8", newline="\n")

    assert len(documents) >= 6
    assert WEB_TREES.read_text(encoding="utf-8") == expected, WEB_TREES_HINT
