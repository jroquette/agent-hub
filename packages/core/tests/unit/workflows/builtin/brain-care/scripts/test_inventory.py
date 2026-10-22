"""The brain-care pack's ``inventory.py`` (AGH-487), in process: the hub's always-loaded context,
its size estimate and the files past the known limits."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/brain-care/scripts/inventory.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.brain-care.scripts.inventory"


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


def write(root: Path, path: str, text: str) -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")


def a_skill(
    root: Path, name: str, description: str, *, typed_only: bool = False, body: str = ""
) -> None:
    head = [f"name: {name}", f"description: {description}"]
    if typed_only:
        head.append("disable-model-invocation: true")
    text = "\n".join(["---", *head, "---", f"# /{name}", "", body or "Steps.", ""])
    write(root, f".claude/skills/{name}/SKILL.md", text)


def inventory(root: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    assert load().main(["--root", str(root)]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def by_path(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["path"]: item for item in found["files"]}


def test_names_files_over_limit_when_context_over_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "CLAUDE.md", "@AGENTS.md\n@docs/rules.md\n")
    write(tmp_path, "AGENTS.md", "rule\n" * 50)
    write(tmp_path, "docs/rules.md", "line\n" * 240)
    a_skill(tmp_path, "big", "d" * 1100)
    a_skill(tmp_path, "small", "Short.")

    found = inventory(tmp_path, capsys)

    assert found["over"] == [
        {"path": "docs/rules.md", "rule": "memory file over 200 lines", "value": 240, "limit": 200},
        {
            "path": ".claude/skills/big/SKILL.md",
            "rule": "skill description over 1,024 characters",
            "value": 1100,
            "limit": 1024,
        },
    ]
    assert "docs/rules.md" in found["summary"]
    assert ".claude/skills/big/SKILL.md" in found["summary"]
    assert "AGENTS.md" in by_path(found)
    assert "estimate" in found["summary"]


def test_flags_agents_when_descriptions_reach_fifteen_thousand_tokens(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for n in range(4):
        text = f"---\nname: a{n}\ndescription: {'x' * 15000}\n---\nBody.\n"
        write(tmp_path, f".claude/agents/a{n}.md", text)

    found = inventory(tmp_path, capsys)

    assert found["over"] == [
        {
            "path": ".claude/agents/",
            "rule": "agent descriptions near 15,000 tokens",
            "value": 15000,
            "limit": 15000,
        }
    ]


def test_skips_body_when_skill_disables_model_invocation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a_skill(tmp_path, "typed", "Typed only.", typed_only=True, body="b" * 4000)
    a_skill(tmp_path, "loaded", "d" * 40, body="b" * 4000)

    found = inventory(tmp_path, capsys)

    files = by_path(found)
    assert files[".claude/skills/loaded/SKILL.md"]["kind"] == "skill"
    assert files[".claude/skills/typed/SKILL.md"]["kind"] == "skill (typed only)"
    # Only the loaded skill's description counts; bodies load only when used.
    assert found["total_tokens"] == 10
    assert any(item["kind"] == "skill body" for item in found["files"])


def test_marks_managed_when_hub_lock_says_managed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "AGENTS.md", "managed\n")
    write(tmp_path, "AGENTS.project.md", "seeded\n")
    write(tmp_path, "CLAUDE.md", "@AGENTS.md\n@AGENTS.project.md\n")
    lock = {
        "files": {
            "AGENTS.md": {"ownership": "managed", "sha256": "0" * 64},
            "AGENTS.project.md": {"ownership": "seeded"},
        }
    }
    write(tmp_path, "hub.lock", json.dumps(lock))

    files = by_path(inventory(tmp_path, capsys))

    assert files["AGENTS.md"]["managed"] is True
    assert files["AGENTS.project.md"]["managed"] is False
    assert files["CLAUDE.md"]["managed"] is False


def test_estimates_tokens_as_chars_over_four(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "CLAUDE.md", "x" * 9)

    found = inventory(tmp_path, capsys)

    assert by_path(found)["CLAUDE.md"] == {
        "path": "CLAUDE.md",
        "kind": "memory",
        "lines": 1,
        "chars": 9,
        "tokens": 3,
        "managed": False,
    }
    assert found["total_tokens"] == 3


def test_lists_unreadable_when_import_leaves_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "hub"
    write(tmp_path, "outside.md", "secret\n")
    write(root, "CLAUDE.md", "@../outside.md\n@~/notes.md\n@missing.md\n")
    write(root, "big.md", "x" * (1024 * 1024 + 1))
    write(root, "AGENTS.md", "@big.md\n")
    (root / "bad.md").write_bytes(b"\xff\n")
    write(root, ".claude/rules/r.md", "@../../bad.md\n")

    found = inventory(root, capsys)

    assert found["unreadable"] == [
        {"path": "../outside.md", "reason": "outside the hub"},
        {"path": "~/notes.md", "reason": "outside the hub"},
        {"path": "missing.md", "reason": "missing"},
        {"path": "big.md", "reason": "larger than 1 MiB"},
        {"path": "bad.md", "reason": "not UTF-8"},
    ]
    assert "outside.md" not in json.dumps(found["files"])


def test_stops_imports_when_deeper_than_four(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "CLAUDE.md", "@d1.md\n")
    for n in range(1, 6):
        write(tmp_path, f"d{n}.md", f"@d{n + 1}.md\n" if n < 5 else "end\n")

    found = inventory(tmp_path, capsys)

    assert {"d1.md", "d2.md", "d3.md", "d4.md"} <= set(by_path(found))
    assert "d5.md" not in by_path(found)
    assert found["unreadable"] == [{"path": "d5.md", "reason": "deeper than 4 imports"}]


def test_keeps_rule_with_paths_out_of_total_when_rules_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, ".claude/rules/always.md", "a" * 40)
    write(tmp_path, ".claude/rules/scoped.md", "---\npaths: [src/**]\n---\n" + "s" * 400)

    found = inventory(tmp_path, capsys)

    assert set(by_path(found)) == {".claude/rules/always.md"}
    assert found["total_tokens"] == 10


def test_exits_two_when_root_not_a_folder(tmp_path: Path) -> None:
    assert load().main(["--root", str(tmp_path / "missing")]) == 2
