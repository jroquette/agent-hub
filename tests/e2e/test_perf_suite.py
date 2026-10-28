"""``make perf``'s fixture generator (``python -m scripts.perf.fixture``) as a subprocess: the
database it writes, read back with stdlib ``sqlite3``."""

import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory

from agent_hub.storage.migration import alembic_config

type Run = Callable[..., subprocess.CompletedProcess[str]]

EVENTS = 2_000
BUILD_SECONDS = 300
CANARY = "canary-from-a-real-home-7f3e9b"
# Every column of ``events`` the store does not mint itself (spec AC-6), in append order.
STABLE_ROWS = (
    "SELECT id, project, session, type, source, source_id, timestamp, payload, repo, agent,"
    " workflow, step FROM events ORDER BY id"
)


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def _build(
    run: Run,
    out: Path,
    *,
    home: Path,
    args: tuple[str, ...] = ("--events", str(EVENTS)),
    extra_env: Mapping[str, str] | None = None,
) -> None:
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": ".",
        "HOME": str(home),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        **(extra_env or {}),
    }
    result = run(
        [sys.executable, "-m", "scripts.perf.fixture", *args, "--out", str(out)],
        env=env,
        timeout=BUILD_SECONDS,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert out.is_file()


def _rows(database: Path, query: str) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(query).fetchall()


def test_writes_every_planned_event_when_built(tmp_path: Path, run: Run) -> None:
    out = tmp_path / "out" / "fixture.db"
    out.parent.mkdir()

    _build(run, out, home=_home(tmp_path))

    assert sorted(path.name for path in out.parent.iterdir()) == ["fixture.db"]
    assert _rows(out, "SELECT count(*) FROM events") == [(EVENTS,)]


def test_writes_identical_rows_when_built_twice_with_one_seed(tmp_path: Path, run: Run) -> None:
    first, second = tmp_path / "a.db", tmp_path / "b.db"

    _build(run, first, home=_home(tmp_path))
    _build(run, second, home=_home(tmp_path))

    rows = _rows(first, STABLE_ROWS)
    assert len(rows) == EVENTS
    assert _rows(second, STABLE_ROWS) == rows


def test_stamps_the_alembic_head_when_built(tmp_path: Path, run: Run) -> None:
    head = ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()
    assert head is not None
    out = tmp_path / "fixture.db"

    _build(run, out, home=_home(tmp_path))

    assert _rows(out, "SELECT version_num FROM alembic_version") == [(head,)]


def test_reads_nothing_from_home_when_home_holds_a_transcript(tmp_path: Path, run: Run) -> None:
    home = _home(tmp_path)
    transcript = home / ".claude" / "projects" / "x" / "s.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(f'{{"type": "user", "message": "{CANARY}"}}\n', "utf-8")
    beside = tmp_path / "out" / "events.jsonl"
    beside.parent.mkdir()
    beside.write_text(f'{{"session": "{CANARY}"}}\n', "utf-8")
    assert CANARY in transcript.read_text("utf-8")
    out = beside.parent / "fixture.db"

    _build(run, out, home=home)

    rows = _rows(out, "SELECT * FROM events")
    assert len(rows) == EVENTS
    assert [row for row in rows if CANARY in repr(row)] == []


def test_reads_the_event_count_from_perf_events_when_no_flag_is_given(
    tmp_path: Path, run: Run
) -> None:
    out = tmp_path / "fixture.db"

    _build(run, out, home=_home(tmp_path), args=(), extra_env={"PERF_EVENTS": "1500"})

    assert _rows(out, "SELECT count(*) FROM events") == [(1_500,)]
