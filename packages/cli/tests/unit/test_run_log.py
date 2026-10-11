import datetime
import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_hub.cli import run_log
from agent_hub.cli.run_log import RunLog, new_run_id
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.storage.errors import StorageError

UTC = datetime.UTC


@pytest.fixture
def tokyo_time(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The process's local time is UTC+9 (a POSIX TZ, no tz database needed)."""
    monkeypatch.setenv("TZ", "JST-9")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def at(moment: datetime.datetime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_log, "now", lambda: moment)


def a_log(hub: Path) -> RunLog:
    return RunLog(hub=hub, run_id="ab12cd34", issue_id="DEM-1", repo="demo-api")


@pytest.mark.usefixtures("tokyo_time")
def test_names_files_by_local_date_when_utc_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(datetime.datetime(2026, 1, 15, 23, 30, tzinfo=UTC), monkeypatch)
    log = a_log(tmp_path)

    log.record("picked", {"transport": "api"})
    log.inbox("- DEM-1 (demo-api) run ab12cd34: FAILED at PICKED; $0.00")

    assert sorted(path.name for path in (tmp_path / ".agent-runs").iterdir()) == [
        "2026-01-16.jsonl"
    ]
    assert sorted(path.name for path in (tmp_path / "brain" / "_inbox" / "runs").iterdir()) == [
        "2026-01-16.md"
    ]
    (line,) = (tmp_path / ".agent-runs" / "2026-01-16.jsonl").read_text().splitlines()
    assert json.loads(line)["ts"] == "2026-01-15T23:30:00+00:00"


def test_writes_utc_seconds_when_ts_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plus_two = datetime.timezone(datetime.timedelta(hours=2))
    at(datetime.datetime(2026, 1, 15, 23, 30, 5, 123456, tzinfo=plus_two), monkeypatch)
    log = a_log(tmp_path)
    log.state = Stage.VERIFYING

    log.record("gate_ok", {"gate": "make check"})

    (path,) = (tmp_path / ".agent-runs").iterdir()
    assert json.loads(path.read_text()) == {
        "ts": "2026-01-15T21:30:05+00:00",
        "run": "ab12cd34",
        "issue": "DEM-1",
        "repo": "demo-api",
        "state": "VERIFYING",
        "event": "gate_ok",
        "live": True,
        "gate": "make check",
    }


def test_appends_one_line_per_record_when_called_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(datetime.datetime(2026, 1, 15, 10, 0, tzinfo=UTC), monkeypatch)
    log = a_log(tmp_path)

    log.record("picked")
    log.record("worktree_ready", {"path": "x"})

    (path,) = (tmp_path / ".agent-runs").iterdir()
    assert [json.loads(line)["event"] for line in path.read_text().splitlines()] == [
        "picked",
        "worktree_ready",
    ]


def test_makes_eight_hex_characters_when_run_id_drawn() -> None:
    ids = {new_run_id() for _ in range(20)}

    assert len(ids) == 20
    assert all(len(run_id) == 8 and int(run_id, 16) >= 0 for run_id in ids)


class _BrokenStore:
    def append(self, events: object) -> object:
        raise StorageError("disk full")

    def read_all(self) -> list[object]:
        return []


def _hub_with_project(tmp_path: Path, name: str = "demo") -> Path:
    (tmp_path / "hub.json").write_text(json.dumps({"project": {"name": name}}))
    return tmp_path


def test_appends_executor_events_when_records_written_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(datetime.datetime(2026, 1, 15, 9, 0, tzinfo=UTC), monkeypatch)
    store = InMemoryEventStore()
    log = RunLog(
        hub=_hub_with_project(tmp_path, "acme"),
        run_id="ab12cd34",
        issue_id="DEM-1",
        repo="demo-api",
        event_store=lambda: store,
    )

    log.record("picked", {"budget": 3.0, "max_turns": 40, "model": "sonnet", "transport": "api"})
    log.state = Stage.WORKTREE
    log.record("worktree_ready", {"path": "/w"})

    events = store.read_all()
    assert [(event.type, event.step) for event in events] == [
        ("step.start", "pick"),
        ("step.end", "pick"),
        ("step.start", "worktree"),
    ]
    assert {event.project for event in events} == {"acme"}
    assert {event.session for event in events} == {"run:ab12cd34"}


def test_warns_once_and_keeps_writing_records_when_store_fails_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    at(datetime.datetime(2026, 1, 15, 9, 0, tzinfo=UTC), monkeypatch)
    log = RunLog(
        hub=_hub_with_project(tmp_path),
        run_id="ab12cd34",
        issue_id="DEM-1",
        repo="demo-api",
        event_store=_BrokenStore,
    )

    log.record("picked", {})
    log.record("again", {})

    assert capsys.readouterr().err == "hub run: event store unavailable: disk full\n"
    (records,) = (tmp_path / ".agent-runs").iterdir()
    assert len(records.read_text().splitlines()) == 2


def test_warns_once_when_store_cannot_open_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    at(datetime.datetime(2026, 1, 15, 9, 0, tzinfo=UTC), monkeypatch)
    calls: list[int] = []

    def failing_open() -> InMemoryEventStore:
        calls.append(1)
        raise OSError("read-only file system")

    log = RunLog(
        hub=tmp_path, run_id="ab12cd34", issue_id="DEM-1", repo="demo-api", event_store=failing_open
    )

    log.record("picked", {})
    log.record("failed", {"stage": "PICKED", "reason": "x"})

    assert capsys.readouterr().err == "hub run: event store unavailable: read-only file system\n"
    assert calls == [1]
