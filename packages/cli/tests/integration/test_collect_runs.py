"""``hub collect --runs PATH``: backfill ``hub run`` records as executor events (AC-200.13)."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import collect
from agent_hub.cli.main import app
from agent_hub.core.testing.run_lines import (
    run_lines_failed_in_verify,
    run_lines_picked_to_reported,
)
from agent_hub.storage.event_store import open_event_store


def _collect(args: Sequence[str], env: dict[str, str] | None = None) -> Result:
    return CliRunner().invoke(app, ["collect", *args], env=env)


def _write(path: Path, records: Sequence[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def test_stores_stages_and_run_ends_then_only_duplicates_when_runs_file_collected_twice(
    tmp_path: Path,
) -> None:
    records = run_lines_picked_to_reported("1a2b3c4d") + run_lines_failed_in_verify(
        loops=1, run_id="5e6f7a8b"
    )
    path = _write(tmp_path / ".agent-runs" / "2026-10-11.jsonl", records)
    db = tmp_path / "events.db"
    args = ["--runs", str(path), "--project", "demo", "--db", str(db)]

    first = _collect(args)
    second = _collect(args)

    assert first.exit_code == 0, first.output
    stored = open_event_store(db).read_all()
    assert second.stdout == f"appended 0, duplicates {len(stored)}\n"
    for run, stages in (("1a2b3c4d", 5), ("5e6f7a8b", 4)):
        mine = [event for event in stored if event.session == f"run:{run}"]
        assert len([e for e in mine if e.type == "step.start"]) == stages
        assert len([e for e in mine if e.type == "step.end"]) == stages
        assert len([e for e in mine if e.type == "run.end"]) == 1
    ends = {event.session: event.payload["status"] for event in stored if event.type == "run.end"}
    assert ends == {"run:1a2b3c4d": "done", "run:5e6f7a8b": "failed"}


def test_reads_every_jsonl_file_when_path_is_runs_folder(tmp_path: Path) -> None:
    folder = tmp_path / "hub" / ".agent-runs"
    _write(folder / "2026-10-10.jsonl", run_lines_picked_to_reported("aaaa1111"))
    _write(folder / "2026-10-11.jsonl", run_lines_picked_to_reported("bbbb2222"))
    _write(folder / "notes.txt", [{"ignored": True}])
    _write(folder / "nested" / "2026-10-12.jsonl", [{"not": "read"}])
    (tmp_path / "hub" / "hub.json").write_text('{"project": {"name": "acme"}}', encoding="utf-8")
    db = tmp_path / "events.db"

    result = _collect(["--runs", str(folder), "--db", str(db)])

    assert result.exit_code == 0, result.output
    stored = open_event_store(db).read_all()
    assert {event.session for event in stored} == {"run:aaaa1111", "run:bbbb2222"}
    assert {event.project for event in stored} == {"acme"}


def test_rejects_batch_naming_file_and_line_when_record_invalid_rejects(tmp_path: Path) -> None:
    records = run_lines_picked_to_reported()
    records[2] = records[2] | {"state": "DANCING"}
    path = _write(tmp_path / "runs.jsonl", records)
    (tmp_path / "bad.jsonl").write_text("{not json\n", encoding="utf-8")
    db = tmp_path / "events.db"

    result = _collect(["--runs", str(tmp_path), "--project", "demo", "--db", str(db)])

    assert result.exit_code == 1
    lines = result.stderr.splitlines()
    assert lines[0].startswith(f'"{tmp_path / "bad.jsonl"}": line 1: invalid JSON')
    assert lines[1].startswith(f'"{path}": line 3: state: expected one of PICKED')
    assert not db.exists()


def test_rejects_folder_when_more_files_than_limit_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect, "MAX_RUN_FILES", 2)
    for day in range(3):
        _write(tmp_path / f"2026-10-1{day}.jsonl", run_lines_picked_to_reported(f"run0000{day}"))

    result = _collect(["--runs", str(tmp_path), "--project", "demo"])

    assert result.exit_code == 1
    assert result.stderr == f'error: "{tmp_path}": more than 2 .jsonl files\n'


def test_rejects_file_when_larger_than_limit_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect, "MAX_RUN_FILE_BYTES", 10)
    path = _write(tmp_path / "runs.jsonl", run_lines_picked_to_reported())

    result = _collect(["--runs", str(path), "--project", "demo"])

    assert result.exit_code == 1
    assert result.stderr.startswith(f'error: cannot read "{path}": larger than 10 bytes')


def test_rejects_path_when_runs_path_missing_rejects(tmp_path: Path) -> None:
    result = _collect(["--runs", str(tmp_path / "nope"), "--project", "demo"])

    assert result.exit_code == 1
    assert result.stderr.startswith("error: input file not found")
