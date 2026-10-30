"""The pre-parsed built-ins (AGH-636, AC-26): a table keyed by the SHA-256 of each built-in file's
bytes, holding what the strict loader reads from it; a broken shipped table names its file."""

import hashlib
import json
from pathlib import Path

import pytest

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
