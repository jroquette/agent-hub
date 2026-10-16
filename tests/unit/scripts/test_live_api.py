import os
from pathlib import Path

from scripts.live_api import changed, snapshot


def _source(root: Path, relative: str, mtime: float = 1_000.0) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", "utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_lists_only_package_sources_when_taking_snapshot(tmp_path: Path) -> None:
    kept = _source(tmp_path, "packages/core/src/agent_hub/core/a.py")
    _source(tmp_path, "packages/core/tests/unit/test_a.py")
    _source(tmp_path, "scripts/tool.py")
    _source(tmp_path, "packages/core/src/agent_hub/core/notes.md")

    assert snapshot(tmp_path) == {kept: 1_000.0}


def test_finds_nothing_when_snapshots_match(tmp_path: Path) -> None:
    _source(tmp_path, "packages/core/src/agent_hub/core/a.py")

    assert changed(snapshot(tmp_path), snapshot(tmp_path)) == []


def test_names_added_removed_and_modified_files_when_snapshots_differ(tmp_path: Path) -> None:
    kept = _source(tmp_path, "packages/core/src/agent_hub/core/kept.py")
    modified = _source(tmp_path, "packages/core/src/agent_hub/core/modified.py")
    removed = _source(tmp_path, "packages/api/src/agent_hub/api/removed.py")
    before = snapshot(tmp_path)

    removed.unlink()
    os.utime(modified, (2_000.0, 2_000.0))
    added = _source(tmp_path, "packages/cli/src/agent_hub/cli/added.py")

    assert changed(before, snapshot(tmp_path)) == sorted([added, modified, removed])
    assert kept not in changed(before, snapshot(tmp_path))
