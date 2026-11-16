"""The brain-care pack's ``check_managed.py`` (AGH-487), in process: a trim commit touches no file
``hub.lock`` (at the base) records as managed."""

import importlib.util
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/brain-care/scripts/check_managed.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.brain-care.scripts.check_managed"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_worktree(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "wt"
    root.mkdir()
    lock = {
        "files": {
            "AGENTS.md": {"ownership": "managed", "sha256": "0" * 64},
            "AGENTS.project.md": {"ownership": "seeded"},
        }
    }
    (root / "hub.lock").write_text(json.dumps(lock))
    for name in ("AGENTS.md", "AGENTS.project.md"):
        (root / name).write_text("rules\n" * 10)
    git(root, "init", "-q", "-b", "trunk")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    return root, git(root, "rev-parse", "HEAD")


def trimmed(root: Path, *names: str) -> None:
    for name in names:
        (root / name).write_text("rules\n")
    git(root, "commit", "-qam", "docs(brain): trim always-loaded context")


def check(root: Path, base: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, Any]:
    code = load().main(["--worktree", str(root), "--base", base])
    out = capsys.readouterr()
    return code, json.loads(out.out) if code == 0 else out.err


def test_passes_when_trim_changes_only_unmanaged_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = a_worktree(tmp_path)
    trimmed(root, "AGENTS.project.md")

    assert check(root, base, capsys) == (0, {"changed": ["AGENTS.project.md"], "managed": []})


def test_refuses_trim_when_it_changes_a_managed_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = a_worktree(tmp_path)
    trimmed(root, "AGENTS.md", "AGENTS.project.md")

    code, err = check(root, base, capsys)

    assert code == 1
    assert "AGENTS.md" in err
    assert "hub.json" in err


def test_reads_lock_from_base_when_trim_rewrote_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = a_worktree(tmp_path)
    (root / "hub.lock").write_text(json.dumps({"files": {}}))
    trimmed(root, "AGENTS.md")

    code, err = check(root, base, capsys)

    assert code == 1
    assert "AGENTS.md" in err
    assert "hub.lock" in err


def test_refuses_uncommitted_change_when_managed_file_dirty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = a_worktree(tmp_path)
    (root / "AGENTS.md").write_text("left\n")

    assert check(root, base, capsys)[0] == 1


def test_exits_one_when_base_unknown(tmp_path: Path) -> None:
    root, _ = a_worktree(tmp_path)

    assert load().main(["--worktree", str(root), "--base", "0" * 40]) == 1
