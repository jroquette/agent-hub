"""``hub collect --transcript FILE``: backfill a Claude Code transcript as metadata (AC-200.11)."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import collect
from agent_hub.cli.main import app
from agent_hub.core.testing.transcript_lines import (
    a_text_block,
    a_thinking_block,
    a_tool_result_line,
    a_tool_use_block,
    a_usage,
    a_user_line,
    an_assistant_line,
    transcript_text,
)
from agent_hub.storage.event_store import open_event_store

SENTINEL = "SENTINEL-transcript-body"


def _collect(args: Sequence[str]) -> Result:
    return CliRunner().invoke(app, ["collect", *args])


def _transcript(tmp_path: Path) -> Path:
    lines = [
        a_user_line(f"add the export {SENTINEL}"),
        an_assistant_line(
            [a_thinking_block(f"plan {SENTINEL}")], usage=a_usage(900, 120), message_id="msg_1"
        ),
        an_assistant_line([a_text_block(f"I will run it {SENTINEL}")], message_id="msg_1"),
        an_assistant_line(
            [a_tool_use_block("toolu_1", "Bash", {"command": "make check-fast"})],
            message_id="msg_2",
        ),
        a_tool_result_line("toolu_1", content=f"ok {SENTINEL}"),
    ]
    path = tmp_path / "session-1.jsonl"
    path.write_text(transcript_text(lines), encoding="utf-8")
    return path


def test_appends_metadata_then_reports_duplicates_when_transcript_collected_twice(
    tmp_path: Path,
) -> None:
    path = _transcript(tmp_path)
    db = tmp_path / "events.db"
    args = ["--transcript", str(path), "--project", "demo", "--db", str(db)]

    first = _collect(args)
    second = _collect(args)

    assert first.exit_code == 0, first.output
    stored = open_event_store(db).read_all()
    assert first.stdout == f"appended {len(stored)}, duplicates 0\n"
    assert second.exit_code == 0
    assert second.stdout == f"appended 0, duplicates {len(stored)}\n"
    assert {event.type for event in stored} == {"message", "reasoning", "tool.call", "tool.result"}
    assert {event.source for event in stored} == {"transcript"}
    assert {event.project for event in stored} == {"demo"}
    assert all(SENTINEL not in event.model_dump_json() for event in stored)
    call = next(event for event in stored if event.type == "tool.call")
    assert call.payload["command"] == "make check-fast"


def test_takes_project_from_hub_when_project_option_absent(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "hub.json").write_text('{"project": {"name": "acme"}}', encoding="utf-8")
    db = tmp_path / "events.db"

    result = CliRunner().invoke(
        app,
        ["collect", "--transcript", str(_transcript(tmp_path)), "--db", str(db)],
        env={"AGENT_HUB_ROOT": str(hub)},
    )

    assert result.exit_code == 0, result.output
    assert {event.project for event in open_event_store(db).read_all()} == {"acme"}


def test_fails_when_no_project_known(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "events.db"

    result = _collect(["--transcript", str(_transcript(tmp_path)), "--db", str(db)])

    assert result.exit_code == 1
    assert result.stderr == "error: no project: pass --project NAME or run in a hub folder\n"
    assert not db.exists()


def test_reports_each_bad_line_and_writes_nothing_when_bad_line(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(transcript_text([a_user_line()]) + "not json\n" + "[1]\n", encoding="utf-8")
    db = tmp_path / "events.db"

    result = _collect(["--transcript", str(path), "--project", "demo", "--db", str(db)])

    assert result.exit_code == 1
    assert result.stderr.splitlines() == [
        "line 2: invalid JSON: Expecting value",
        "line 3: expected a JSON object",
    ]
    assert not db.exists()


def test_reports_line_when_line_longer_than_one_mebibyte_too_large(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text(transcript_text([a_user_line("x" * 1_100_000)]), encoding="utf-8")
    db = tmp_path / "events.db"

    result = _collect(["--transcript", str(path), "--project", "demo", "--db", str(db)])

    assert result.exit_code == 1
    assert result.stderr == "line 1: line longer than 1048576 bytes\n"
    assert not db.exists()


def test_refuses_file_when_larger_than_limit_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collect, "MAX_TRANSCRIPT_BYTES", 100)
    path = _transcript(tmp_path)
    db = tmp_path / "events.db"

    result = _collect(["--transcript", str(path), "--project", "demo", "--db", str(db)])

    assert result.exit_code == 1
    assert result.stderr.startswith(f'error: cannot read "{path}": larger than 100 bytes')
    assert not db.exists()


def test_refuses_input_when_transcript_is_not_a_regular_file(tmp_path: Path) -> None:
    db = tmp_path / "events.db"

    missing = _collect(["--transcript", str(tmp_path / "nope.jsonl"), "--project", "d"])
    folder = _collect(["--transcript", str(tmp_path), "--project", "d", "--db", str(db)])

    assert missing.exit_code == 1
    assert missing.stderr.startswith("error: input file not found")
    assert folder.exit_code == 1
    assert "not a regular file" in folder.stderr
    assert not db.exists()


def test_labels_repo_and_agent_like_live_tail_when_cwd_in_hub_repo(tmp_path: Path) -> None:
    hub = tmp_path / "work" / "demo-hub"
    hub.mkdir(parents=True)
    (hub / "hub.json").write_text(
        '{"project": {"name": "acme"}, "repos": [{"dir": "demo-api"}]}', encoding="utf-8"
    )
    path = tmp_path / "agent-7.jsonl"
    path.write_text(
        transcript_text([a_user_line(cwd=str(tmp_path / "work" / "demo-api"))]), encoding="utf-8"
    )
    db = tmp_path / "events.db"

    result = CliRunner().invoke(
        app,
        ["collect", "--transcript", str(path), "--agent", "Explore", "--db", str(db)],
        env={"AGENT_HUB_ROOT": str(hub)},
    )

    assert result.exit_code == 0, result.output
    [event] = open_event_store(db).read_all()
    assert (event.project, event.repo, event.agent) == ("acme", "demo-api", "Explore")


def test_fails_and_writes_nothing_when_project_longer_than_cap(tmp_path: Path) -> None:
    db = tmp_path / "events.db"

    result = _collect(
        ["--transcript", str(_transcript(tmp_path)), "--project", "p" * 201, "--db", str(db)]
    )

    assert result.exit_code == 1
    assert result.stderr == "error: --project: longer than 200 characters\n"
    assert not db.exists()
