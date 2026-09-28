import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.events.event import Event
from agent_hub.core.testing.builders import an_event, events_to_jsonl
from agent_hub.storage.event_store import open_event_store


def _collect(
    args: Sequence[str], *, stdin: str | None = None, env: Mapping[str, str | None] | None = None
) -> Result:
    return CliRunner().invoke(app, ["collect", *args], input=stdin, env=env)


def _write_jsonl(path: Path, events: Sequence[Event]) -> Path:
    path.write_text(events_to_jsonl(events), encoding="utf-8")
    return path


def _stored(db_path: Path) -> list[Event]:
    return open_event_store(db_path).read_all()


def test_appends_then_reports_duplicates_when_file_collected_twice(tmp_path: Path) -> None:
    events = [an_event(), an_event(), an_event()]
    file = _write_jsonl(tmp_path / "events.jsonl", events)
    db_path = tmp_path / "events.db"

    first = _collect([str(file), "--db", str(db_path)])
    second = _collect([str(file), "--db", str(db_path)])

    assert first.exit_code == 0
    assert first.stdout == "appended 3, duplicates 0\n"
    assert second.exit_code == 0
    assert second.stdout == "appended 0, duplicates 3\n"
    assert _stored(db_path) == events


def test_reads_stdin_when_no_file_argument(tmp_path: Path) -> None:
    events = [an_event(), an_event()]
    db_path = tmp_path / "events.db"

    result = _collect(["--db", str(db_path)], stdin=events_to_jsonl(events))

    assert result.exit_code == 0
    assert result.stdout == "appended 2, duplicates 0\n"
    assert _stored(db_path) == events


def test_reads_stdin_when_argument_is_dash(tmp_path: Path) -> None:
    events = [an_event(), an_event()]
    db_path = tmp_path / "events.db"

    result = _collect(["-", "--db", str(db_path)], stdin=events_to_jsonl(events))

    assert result.exit_code == 0
    assert result.stdout == "appended 2, duplicates 0\n"
    assert _stored(db_path) == events


def test_rejects_batch_when_lines_invalid(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    stored = an_event()
    open_event_store(db_path).append([stored])
    without_source_id = an_event().model_dump(mode="json")
    del without_source_id["source_id"]
    lines = [
        an_event().model_dump_json(),
        an_event().model_dump_json(),
        "not json",
        an_event().model_dump_json(),
        json.dumps(without_source_id),
    ]
    file = tmp_path / "events.jsonl"
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _collect([str(file), "--db", str(db_path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    error_lines = result.stderr.splitlines()
    assert len(error_lines) == 2
    assert error_lines[0].startswith("line 3: ")
    assert "JSON" in error_lines[0]
    assert error_lines[1].startswith("line 5: ")
    assert "source_id" in error_lines[1]
    assert _stored(db_path) == [stored]


def test_rejects_batch_when_key_conflicts_with_stored_event(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    stored = an_event(source="github", payload={"state": "open"})
    open_event_store(db_path).append([stored])
    changed = an_event(source="github", source_id=stored.source_id, payload={"state": "closed"})
    file = _write_jsonl(tmp_path / "events.jsonl", [an_event(), changed])

    result = _collect([str(file), "--db", str(db_path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("line 2: conflict: ")
    assert "github" in result.stderr
    assert stored.source_id in result.stderr
    assert _stored(db_path) == [stored]


def test_counts_duplicate_when_file_repeats_event(tmp_path: Path) -> None:
    event = an_event()
    file = _write_jsonl(tmp_path / "events.jsonl", [event, event])
    db_path = tmp_path / "events.db"

    result = _collect([str(file), "--db", str(db_path)])

    assert result.exit_code == 0
    assert result.stdout == "appended 1, duplicates 1\n"
    assert _stored(db_path) == [event]


def test_writes_env_database_when_db_flag_absent(tmp_path: Path) -> None:
    file = _write_jsonl(tmp_path / "events.jsonl", [an_event()])
    env_db = tmp_path / "env.db"

    result = _collect([str(file)], env={"AGENT_HUB_DB": str(env_db)})

    assert result.exit_code == 0
    assert len(_stored(env_db)) == 1
    assert not (tmp_path / "xdg").exists()


def test_prefers_flag_when_env_and_flag_given(tmp_path: Path) -> None:
    file = _write_jsonl(tmp_path / "events.jsonl", [an_event()])
    env_db = tmp_path / "env.db"
    flag_db = tmp_path / "flag.db"

    result = _collect([str(file), "--db", str(flag_db)], env={"AGENT_HUB_DB": str(env_db)})

    assert result.exit_code == 0
    assert len(_stored(flag_db)) == 1
    assert not env_db.exists()


def test_writes_xdg_database_when_no_flag_or_env(tmp_path: Path) -> None:
    file = _write_jsonl(tmp_path / "events.jsonl", [an_event()])
    xdg = tmp_path / "custom-xdg"

    result = _collect([str(file)], env={"XDG_DATA_HOME": str(xdg), "AGENT_HUB_DB": None})

    assert result.exit_code == 0
    assert len(_stored(xdg / "agent-hub" / "agent-hub.db")) == 1


def test_writes_home_database_when_xdg_unset(tmp_path: Path) -> None:
    file = _write_jsonl(tmp_path / "events.jsonl", [an_event()])
    home = tmp_path / "custom-home"

    result = _collect([str(file)], env={"XDG_DATA_HOME": None, "HOME": str(home)})

    assert result.exit_code == 0
    assert len(_stored(home / ".local" / "share" / "agent-hub" / "agent-hub.db")) == 1


def test_fails_without_creating_database_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    db_path = tmp_path / "data" / "events.db"

    result = _collect([str(missing), "--db", str(db_path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert str(missing) in result.stderr
    assert "Traceback" not in result.stderr
    assert not db_path.parent.exists()


def test_fails_without_creating_database_when_stdin_not_utf8(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "events.db"

    result = CliRunner().invoke(
        app, ["collect", "--db", str(db_path)], input=b'{"project": "caf\xe9"}\n'
    )

    assert result.exit_code == 1
    assert "stdin" in result.stderr
    assert "UTF-8" in result.stderr
    assert not db_path.parent.exists()


def test_fails_without_creating_database_when_lines_invalid(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "events.db"

    result = _collect(["--db", str(db_path)], stdin="not json\n")

    assert result.exit_code == 1
    assert result.stderr.startswith("line 1: ")
    assert not db_path.parent.exists()


def test_reports_zero_when_file_empty(tmp_path: Path) -> None:
    file = tmp_path / "empty.jsonl"
    file.write_text("", encoding="utf-8")
    db_path = tmp_path / "events.db"

    result = _collect([str(file), "--db", str(db_path)])

    assert result.exit_code == 0
    assert result.stdout == "appended 0, duplicates 0\n"


def test_reports_zero_when_stdin_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    result = _collect(["-", "--db", str(db_path)], stdin="")

    assert result.exit_code == 0
    assert result.stdout == "appended 0, duplicates 0\n"


def test_prints_message_when_database_unusable(tmp_path: Path) -> None:
    file = _write_jsonl(tmp_path / "events.jsonl", [an_event()])
    db_path = tmp_path / "events.db"
    db_path.write_bytes(b"this is not a SQLite database, just synthetic bytes" * 100)

    result = _collect([str(file), "--db", str(db_path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")
    assert "Traceback" not in result.stderr
    assert len(result.stderr.splitlines()) == 1
