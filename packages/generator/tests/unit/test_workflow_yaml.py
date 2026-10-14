"""Strict workflow loader: YAML through a refusing SafeLoader, JSON through the strict reader."""

import pytest

from agent_hub.generator.workflow_yaml import (
    MAX_WORKFLOW_BYTES,
    WorkflowFileError,
    load_workflow_bytes,
)


def _refusal(content: bytes, source: str = "workflows/p/w.yaml") -> WorkflowFileError:
    with pytest.raises(WorkflowFileError) as caught:
        load_workflow_bytes(content, source=source)
    return caught.value


def test_returns_mapping_when_yaml_is_plain() -> None:
    content = (
        b"version: 1\nname: w\nnodes:\n  - id: a\n    type: shell\n    command: [make, check]\n"
    )

    document = load_workflow_bytes(content, source="w.yaml")

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

    assert load_workflow_bytes(content, source="w.yaml") == {"name": "w"}


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

    assert load_workflow_bytes(content, source="w.yaml") == {
        "on": "yes",
        "no_": "off",
        "day": "2026-10-14",
        "legacy_octal": 12,
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
    assert load_workflow_bytes(b"<<: {a: 1}\n", source="w.yaml") == {"<<": {"a": 1}}


def test_refuses_when_bytes_are_not_utf8() -> None:
    error = _refusal(b"name: \xff\n")

    assert error.line is None
    assert "UTF-8" in error.reason


def test_refuses_when_nested_too_deeply() -> None:
    assert "deep" in _refusal(b"a: " + b"[" * 20_000 + b"]" * 20_000 + b"\n").reason


def test_returns_mapping_when_json_given() -> None:
    content = b'{"version": 1, "name": "w", "nodes": [{"id": "a", "type": "halt"}]}'

    document = load_workflow_bytes(content, source="workflows/p/w.json")

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
