"""The pre-parsed built-ins (AGH-636, AC-26): a table keyed by the SHA-256 of each built-in file's
bytes, holding what the strict loader reads from it; a broken shipped table names its file."""

import hashlib
import json
from pathlib import Path

import pytest

from agent_hub.generator import parsed_builtins
from agent_hub.generator.parsed_builtins import (
    TABLE_FILE,
    ParsedBuiltin,
    ParsedBuiltinsError,
    load_table,
    lookup,
    table_text,
)
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import read_workflow_strictly


def _builtin_files() -> list[Path]:
    """Every pack-level ``*.yaml`` built-in (the files discovery reads), hidden names skipped."""
    found = sorted(
        path
        for path in BUILTIN_WORKFLOWS.glob("*/*.yaml")
        if not path.name.startswith(".") and not path.parent.name.startswith(".")
    )
    assert len(found) >= 20, found
    assert BUILTIN_WORKFLOWS / "issue-to-pr" / "issue-to-pr.yaml" in found
    return found


def test_finds_entry_when_builtin_bytes_are_looked_up() -> None:
    for path in _builtin_files():
        content = path.read_bytes()
        source = f"{path.parent.name}/{path.name}"
        strict = read_workflow_strictly(content, source=source)

        entry = lookup(hashlib.sha256(content).digest())

        assert entry is not None, source
        assert entry.sha256 == hashlib.sha256(content).hexdigest()
        assert entry.source == source
        assert entry.document == strict.document, source
        assert dict(entry.lines) == dict(strict.lines), source


def test_finds_nothing_when_one_byte_differs() -> None:
    content = (BUILTIN_WORKFLOWS / "issue-to-pr" / "issue-to-pr.yaml").read_bytes()
    assert lookup(hashlib.sha256(content).digest()) is not None

    assert lookup(hashlib.sha256(content + b"\n").digest()) is None


def test_round_trips_entries_when_table_text_is_read(tmp_path: Path) -> None:
    second = ParsedBuiltin(
        sha256=hashlib.sha256(b"b").hexdigest(),
        source="zeta/z.yaml",
        document={"name": "z", "nodes": [{"id": "a", "type": "halt"}], "on": "yes"},
        lines={(): 1, ("name",): 1, ("nodes",): 2, ("nodes", 0): 3, ("nodes", 0, "id"): 3},
    )
    first = ParsedBuiltin(
        sha256=hashlib.sha256(b"a").hexdigest(),
        source="alpha/a.yaml",
        document={"name": "a", "ratio": -1.5, "n": 7, "flag": True, "nothing": None},
        lines={(): 1, ("name",): 1, ("ratio",): 2},
    )

    text = table_text([second, first])
    table = tmp_path / TABLE_FILE
    table.write_text(text, encoding="utf-8")
    read_back = load_table(table)

    assert read_back == {bytes.fromhex(first.sha256): first, bytes.fromhex(second.sha256): second}
    decoded = json.loads(text)
    assert decoded["format"] == 1
    assert [entry["source"] for entry in decoded["entries"]] == ["alpha/a.yaml", "zeta/z.yaml"]
    assert decoded["entries"][0]["lines"] == [[[], 1], [["name"], 1], [["ratio"], 2]]
    assert len([line for line in text.splitlines() if '"sha256"' in line]) == 2
    assert text.endswith("\n")


@pytest.mark.parametrize(
    "content",
    [None, b'{"format": 1, "entries": [', b'["not", "a", "table"]\n'],
    ids=["missing", "truncated", "not_a_table"],
)
def test_names_table_when_shipped_table_cannot_be_read(
    tmp_path: Path, content: bytes | None
) -> None:
    broken = tmp_path / TABLE_FILE
    if content is not None:
        broken.write_bytes(content)
    assert broken.exists() is (content is not None)

    with pytest.raises(ParsedBuiltinsError) as caught:
        load_table(broken)

    assert TABLE_FILE in str(caught.value)


@pytest.mark.parametrize(
    "content",
    [None, b'{"format": 2, "entries": []}\n'],
    ids=["missing", "wrong_format"],
)
def test_raises_on_every_lookup_when_shipped_resource_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes | None
) -> None:
    if content is not None:
        (tmp_path / TABLE_FILE).write_bytes(content)
    loaded: list[object] = []
    monkeypatch.setattr(parsed_builtins, "_loaded", loaded)
    monkeypatch.setattr(parsed_builtins, "files", lambda package: tmp_path)
    digest = hashlib.sha256(b"name: w\n").digest()

    for _ in range(2):
        with pytest.raises(ParsedBuiltinsError) as caught:
            lookup(digest)
        assert str(tmp_path / TABLE_FILE) in str(caught.value)

    assert loaded == []


def _valid_row() -> dict[str, object]:
    return {
        "sha256": hashlib.sha256(b"a").hexdigest(),
        "source": "alpha/a.yaml",
        "document": {"name": "a"},
        "lines": [[[], 1], [["name"], 1]],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (None, None),
        ("sha256", "ab"),
        ("sha256", hashlib.sha256(b"a").hexdigest().upper()),
        ("source", 3),
        ("document", ["name", "a"]),
        ("lines", {"name": 1}),
        ("lines", [[["name"], 1, 2]]),
        ("lines", [["name", 1]]),
        ("lines", [[["name", 1.5], 1]]),
        ("lines", [[["name"], True]]),
    ],
    ids=[
        "not_a_mapping",
        "short_digest",
        "upper_case_digest",
        "source_not_text",
        "document_not_a_mapping",
        "lines_not_a_list",
        "pair_too_long",
        "path_not_a_list",
        "path_part_a_float",
        "line_a_bool",
    ],
)
def test_names_entry_when_table_entry_is_malformed(
    tmp_path: Path, field: str | None, value: object
) -> None:
    row: object = "not an entry" if field is None else {**_valid_row(), field: value}
    table = tmp_path / TABLE_FILE
    table.write_text(json.dumps({"format": 1, "entries": [_valid_row(), row]}), encoding="utf-8")

    with pytest.raises(ParsedBuiltinsError) as caught:
        load_table(table)

    assert TABLE_FILE in str(caught.value)
    assert "entry 1 is not a valid entry" in str(caught.value)
