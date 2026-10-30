import hashlib
from pathlib import Path

import pytest

from agent_hub.generator.parsed_builtins import ParsedBuiltin, table_text
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import read_workflow_strictly
from scripts.export_parsed_builtins import REPO_ROOT, TABLE_PATH, main


def _rebuilt_table() -> str:
    """The table rebuilt from the strict loader, for every pack-level built-in ``*.yaml``."""
    entries = []
    for path in sorted(BUILTIN_WORKFLOWS.glob("*/*.yaml")):
        if path.name.startswith(".") or path.parent.name.startswith("."):
            continue
        content = path.read_bytes()
        source = f"{path.parent.name}/{path.name}"
        loaded = read_workflow_strictly(content, source=source)
        entries.append(
            ParsedBuiltin(
                sha256=hashlib.sha256(content).hexdigest(),
                source=source,
                document=loaded.document,
                lines=loaded.lines,
            )
        )
    assert len(entries) >= 20, entries
    assert "issue-to-pr/issue-to-pr.yaml" in {entry.source for entry in entries}
    return table_text(entries)


def test_leaves_table_unchanged_when_loader_and_builtins_unchanged() -> None:
    committed = REPO_ROOT / TABLE_PATH
    assert committed.is_file(), f"run make parsed-builtins: {TABLE_PATH} is missing"

    assert committed.read_bytes() == _rebuilt_table().encode()


def test_writes_strict_loader_output_when_run_on_repo_root(tmp_path: Path) -> None:
    target = tmp_path / TABLE_PATH
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8")

    assert main([], root=tmp_path) == 0

    assert target.read_bytes() == _rebuilt_table().encode()


def test_prints_usage_when_arguments_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["extra"], root=tmp_path) == 2

    assert "usage: python -m scripts.export_parsed_builtins" in capsys.readouterr().err
    assert not (tmp_path / TABLE_PATH).exists()
