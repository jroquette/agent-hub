"""The release pack's ``compose.py`` (AGH-494), in process: the release notes."""

import importlib.util
import io
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/release/scripts/compose.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.release.scripts.compose"


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


NOTES = {
    "features": "- The release pack (#250).",
    "fixes": "",
    "doctor": "",
    "migration": "- Run ./hub sync after the bump.",
    "summary": "The release pack.",
}
SYNC = "update .claude/settings.json\ncreate workflows/release/release.yaml"


def compose(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    notes: dict[str, str] = NOTES,
    sync: str = SYNC,
) -> dict[str, Any]:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(notes)))
    argv = ["--version", "0.21.0", "--last-tag", "v0.20.1", "--sync", sync]
    assert load().main(argv) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_holds_five_sections_and_sync_list_when_composed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = compose(monkeypatch, capsys)
    notes = found["notes"]

    headings = [line for line in notes.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Features",
        "## Fixes",
        "## What `hub sync` rewrites in every hub",
        "## Doctor rules added or changed",
        "## Migration steps",
    ]
    assert notes.startswith("v0.21.0 (since v0.20.1)\n\nThe release pack.\n")
    assert "## Features\n\n- The release pack (#250).\n" in notes
    assert "## Fixes\n\nnone\n" in notes
    assert "- update .claude/settings.json\n- create workflows/release/release.yaml\n" in notes
    assert "## Doctor rules added or changed\n\nnone\n" in notes
    assert notes.endswith("## Migration steps\n\n- Run ./hub sync after the bump.\n")
    assert (found["chars"], found["trimmed"]) == (len(notes), False)


def test_says_none_when_sync_list_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notes = compose(monkeypatch, capsys, sync="none")["notes"]

    assert "## What `hub sync` rewrites in every hub\n\nnone\n" in notes


def test_trims_sync_list_to_counts_when_notes_over_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    assert module.MAX_NOTES == 60000
    sync = "\n".join(
        [f"update plugin/hub-workflow/skills/s{n}/SKILL.md" for n in range(300)]
        + [f"create workflows/release/f{n}.yaml" for n in range(200)]
        + ["update Makefile"]
    )
    notes = NOTES | {"features": "x" * 11000, "fixes": "y" * 11000, "doctor": "z" * 6000}
    monkeypatch.setattr(module, "MAX_NOTES", 30000)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(notes)))

    assert module.main(["--version", "0.21.0", "--last-tag", "v0.20.1", "--sync", sync]) == 0
    found = json.loads(capsys.readouterr().out)

    assert found["trimmed"] is True
    assert found["chars"] == len(found["notes"]) <= 30000
    assert "- plugin/: 300 files\n" in found["notes"]
    assert "- workflows/: 200 files\n" in found["notes"]
    assert "- Makefile: 1 file\n" in found["notes"]
    assert "full list in the hub PR" in found["notes"]
    assert "SKILL.md" not in found["notes"]


def test_cuts_notes_when_counts_still_over_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    monkeypatch.setattr(module, "MAX_NOTES", 500)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(NOTES | {"features": "x" * 900})))

    assert module.main(["--version", "0.21.0", "--last-tag", "v0.20.1", "--sync", SYNC]) == 0
    found = json.loads(capsys.readouterr().out)

    assert (found["trimmed"], found["chars"]) == (True, 500)
    assert found["notes"].endswith("…")


@pytest.mark.parametrize("stdin", ["", "[]", '{"features": 1}', "not json"])
def test_exits_two_when_notes_not_sections(monkeypatch: pytest.MonkeyPatch, *, stdin: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))

    assert load().main(["--version", "0.21.0", "--last-tag", "v0.20.1", "--sync", SYNC]) == 2


def test_reads_sync_text_starting_with_a_dash_when_given(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The sync list is data (AGH-480): a leading dash is never read as an option.
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(NOTES)))

    assert load().main(["--version", "0.21.0", "--last-tag", "v0.20.1", "--sync", "-none"]) == 0
    assert json.loads(capsys.readouterr().out)["notes"]
