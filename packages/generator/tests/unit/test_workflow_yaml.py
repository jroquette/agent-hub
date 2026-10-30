"""Strict workflow loader (AC-213.2): YAML through a refusing SafeLoader, JSON through core's
strict reader; each key path's line recorded for the document model's errors (AC-213.1)."""

from pathlib import Path
from uuid import uuid4

import pytest

from agent_hub.core.hub_config.versions import ECHO_LIMIT
from agent_hub.generator import workflow_yaml
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import (
    MAX_CACHED_BYTES,
    MAX_LINE_DEPTH,
    MAX_LINE_ENTRIES,
    MAX_WORKFLOW_BYTES,
    LoadedWorkflow,
    WorkflowFileError,
    load_workflow_bytes,
    read_workflow_strictly,
)


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


# The parse cache (AGH-636): every test builds bytes unique to the run, so the process-wide
# cache never holds them from an earlier test, and counts the strict loader's calls.


def _unique(body: bytes) -> bytes:
    return f"# {uuid4().hex}\n".encode() + body


@pytest.fixture
def strict_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The ``source`` of each call to the strict loader, in order, while the test runs."""
    calls: list[str] = []
    strict = workflow_yaml.read_workflow_strictly

    def counting(content: bytes, *, source: str) -> LoadedWorkflow:
        calls.append(source)
        return strict(content, source=source)

    monkeypatch.setattr(workflow_yaml, "read_workflow_strictly", counting)
    return calls


def test_parses_once_when_same_bytes_are_read_twice(strict_reads: list[str]) -> None:
    content = _unique(b"version: 1\nname: w\nnodes:\n  - id: a\n    type: halt\n")

    first = load_workflow_bytes(content, source="workflows/p/w.yaml")
    second = load_workflow_bytes(content, source="workflows/p/w.yaml")

    assert strict_reads == ["workflows/p/w.yaml"]
    assert first.document == {"version": 1, "name": "w", "nodes": [{"id": "a", "type": "halt"}]}
    assert second == first


def test_parses_again_when_refused_bytes_are_read_twice(strict_reads: list[str]) -> None:
    content = _unique(b"name: w\nschema: &shared {type: object}\n")

    first = _refusal(content)
    second = _refusal(content)

    assert strict_reads == ["workflows/p/w.yaml", "workflows/p/w.yaml"]
    assert (first.line, second.line) == (3, 3)
    assert "anchor" in first.reason
    assert second.reason == first.reason


def test_returns_own_document_when_cached_bytes_are_read_again(strict_reads: list[str]) -> None:
    content = _unique(
        b"on: yes\nno_: off\nday: 2026-10-14\nlegacy_octal: 012\nhex: 0x1f\n"
        b"time: 1:30\ninf: .inf\nflag: True\nnothing: null\nempty:\nratio: -1.5e3\nn: -7\n"
    )
    original = {
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
    first = load_workflow_bytes(content, source="w.yaml")
    assert first.document == original
    first.document["n"] = 0
    first.document["extra"] = True
    del first.document["on"]

    second = load_workflow_bytes(content, source="w.yaml")

    assert strict_reads == ["w.yaml"]
    assert second.document == original
    assert second.lines[("on",)] == 2
    with pytest.raises(TypeError):
        second.lines[("on",)] = 9  # type: ignore[index]


def test_parses_each_format_when_same_bytes_are_read_as_json_and_yaml(
    strict_reads: list[str],
) -> None:
    run = uuid4().hex
    content = f'{{"a": 1, "run": "{run}"}}'.encode()

    as_json = load_workflow_bytes(content, source="x.json")
    as_yaml = load_workflow_bytes(content, source="x.yaml")

    assert strict_reads == ["x.json", "x.yaml"]
    assert as_json.document == {"a": 1, "run": run}
    assert as_yaml.document == {"a": 1, "run": run}


@pytest.mark.parametrize(
    ("files", "size"),
    [(129, 0), (5, 250 * 1024)],
    ids=["entry_count", "input_bytes"],
)
def test_drops_oldest_entry_when_cache_bound_is_reached(
    strict_reads: list[str], files: int, size: int
) -> None:
    run = uuid4().hex
    heads = [f"# {run} {index}\nname: w\n".encode() for index in range(files)]
    contents = [head + b"#" * max(size - len(head) - 1, 0) + b"\n" for head in heads]
    assert len(set(contents)) == files
    assert size == 0 or {len(content) for content in contents} == {size}
    sources = [f"workflows/p/w{index}.yaml" for index in range(files)]
    for content, source in zip(contents, sources, strict=True):
        load_workflow_bytes(content, source=source)
    assert strict_reads == sources

    load_workflow_bytes(contents[0], source=sources[0])
    load_workflow_bytes(contents[-1], source=sources[-1])

    assert strict_reads == [*sources, sources[0]]


# The pre-parsed built-ins (AGH-636, AC-26): a built-in's exact bytes skip the strict parse; any
# other byte string, an edited built-in included, takes the strict path and gets its answer.


def _builtin_files() -> list[Path]:
    found = sorted(
        path
        for path in BUILTIN_WORKFLOWS.glob("*/*.yaml")
        if not path.name.startswith(".") and not path.parent.name.startswith(".")
    )
    assert len(found) >= 20, found
    return found


def _evict_cached_files(strict_reads: list[str]) -> None:
    """Fill the parse cache past its byte bound with unique files, so it holds no built-in."""
    size = 250 * 1024
    count = MAX_CACHED_BYTES // size + 1
    run = uuid4().hex
    for index in range(count):
        head = f"# {run} {index}\nname: w\n".encode()
        load_workflow_bytes(head + b"#" * (size - len(head) - 1) + b"\n", source=f"e{index}.yaml")
    assert len(strict_reads) == count
    strict_reads.clear()


def test_skips_strict_parse_when_builtin_bytes_are_read(strict_reads: list[str]) -> None:
    files = _builtin_files()
    _evict_cached_files(strict_reads)

    loaded = {
        path: load_workflow_bytes(
            path.read_bytes(), source=f"workflows/{path.parent.name}/{path.name}"
        )
        for path in files
    }

    assert strict_reads == []
    for path, result in loaded.items():
        strict = read_workflow_strictly(path.read_bytes(), source=path.name)
        assert result.document == strict.document, path
        assert dict(result.lines) == dict(strict.lines), path


def test_takes_strict_path_when_edited_builtin_is_read(strict_reads: list[str]) -> None:
    content = _unique((BUILTIN_WORKFLOWS / "issue-to-pr" / "issue-to-pr.yaml").read_bytes())

    result = load_workflow_bytes(content, source="workflows/issue-to-pr/issue-to-pr.yaml")

    assert strict_reads == ["workflows/issue-to-pr/issue-to-pr.yaml"]
    strict = read_workflow_strictly(content, source="workflows/issue-to-pr/issue-to-pr.yaml")
    assert result.document == strict.document
    assert dict(result.lines) == dict(strict.lines)


def test_refuses_as_strict_loader_when_edited_builtin_holds_anchor() -> None:
    builtin = (BUILTIN_WORKFLOWS / "issue-to-pr" / "issue-to-pr.yaml").read_bytes()
    assert builtin.endswith(b"\n")
    content = builtin + b"zz_anchored: &a 1\n"
    source = "workflows/issue-to-pr/issue-to-pr.yaml"
    with pytest.raises(WorkflowFileError) as strict:
        read_workflow_strictly(content, source=source)

    refused = _refusal(content, source)

    assert refused.line == content.count(b"\n")
    assert "anchor" in refused.reason
    assert (refused.source, refused.line, refused.reason) == (
        strict.value.source,
        strict.value.line,
        strict.value.reason,
    )
