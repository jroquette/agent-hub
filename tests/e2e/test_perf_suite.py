"""``make perf``'s fixture generator (``python -m scripts.perf.fixture``) as a subprocess: the
database it writes, read back with stdlib ``sqlite3``; and the whole suite
(``python -m scripts.perf.run_suite``) on a small fixture: its table and ``perf.json``."""

import json
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
from scripts.perf.fixture import PAGE_SESSION

type Run = Callable[..., subprocess.CompletedProcess[str]]

EVENTS = 2_000
BUILD_SECONDS = 300
CANARY = "canary-from-a-real-home-7f3e9b"
# Every column of ``events`` the store does not mint itself (spec AC-6), in append order.
STABLE_ROWS = (
    "SELECT id, project, session, type, source, source_id, timestamp, payload, repo, agent,"
    " workflow, step FROM events ORDER BY id"
)
SUITE_SECONDS = 1_200
SHIPPED_BUDGETS = Path(__file__).resolve().parents[2] / "scripts" / "perf" / "budgets.json"
OVER_ROW = ("route", "/api/v1/sessions")
# Plan "Rows (canonical paths)", written out by hand (<SLUG> = search-index).
EXPECTED_ROWS = {
    ("cli", "hub --version"),
    ("cli", "./hub --version (local uvx stand-in)"),
    ("cli", "hub brief --no-network"),
    ("hook", "guard (PreToolUse Bash)"),
    ("hook", "event_sensor (PreToolUse, sensor closed)"),
    ("hook", "post_edit (PostToolUse Edit)"),
    ("hook", "readonly_gate (PreToolUse Bash)"),
    ("hook", "session_end"),
    ("hook", "stop_gate (no changes)"),
    ("hook", "session_start (local uvx stand-in)"),
    ("hook", "pre_compact"),
    ("route", "/api/v1/sessions"),
    ("route", "/api/v1/sessions?issue=AGH-7"),
    ("route", "/api/v1/features"),
    ("route", "/api/v1/features/perf/search-index"),
    ("route", "/api/v1/projects/perf/skills"),
    ("route", "/api/v1/search?q=make"),
    ("route", "/api/v1/live-sessions"),
    ("page", "/"),
    ("page", "/features"),
    ("page", "/features/perf/search-index"),
    ("page", f"/sessions/{PAGE_SESSION}"),
    ("restart", "hub web start → GET /"),
    ("restart", "hub web start → /api/v1/sessions"),
}
KINDS = {"cli", "hook", "route", "page", "restart"}
STATUSES = {"pass", "over", "no budget", "skipped"}
# What a parent may hold to point the page rows at a browser; nothing else is inherited.
BROWSER_VARIABLES = ("PLAYWRIGHT_BROWSERS_PATH", "AGENT_HUB_CHROMIUM")


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


def _budgets_with_sessions_at_zero(path: Path) -> Path:
    shipped = json.loads(SHIPPED_BUDGETS.read_text("utf-8"))
    entries = [entry for entry in shipped["rows"] if (entry["kind"], entry["path"]) == OVER_ROW]
    assert len(entries) == 1
    entries[0]["p95_ms"] = 0
    path.write_text(json.dumps(shipped), "utf-8")
    return path


def test_writes_one_row_per_table_line_when_run_on_a_small_fixture(
    tmp_path: Path, run: Run
) -> None:
    home = _home(tmp_path)
    (tmp_path / "tmp").mkdir()
    out = tmp_path / "out" / "perf.json"
    budgets = _budgets_with_sessions_at_zero(tmp_path / "budgets.json")
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": ".",
        "HOME": str(home),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "TMPDIR": str(tmp_path / "tmp"),
        "PERF_EVENTS": str(EVENTS),
        "PERF_RUNS": "2",
        "PERF_RESTART_RUNS": "1",
        "PERF_OUT": str(out),
        "PERF_CACHE": str(tmp_path / "cache"),
        "PERF_BUDGETS": str(budgets),
        **{name: os.environ[name] for name in BROWSER_VARIABLES if name in os.environ},
    }
    assert "PERF_STRICT" not in env

    result = run([sys.executable, "-m", "scripts.perf.run_suite"], env=env, timeout=SUITE_SECONDS)

    assert result.returncode == 0, result.stdout + result.stderr
    rows = json.loads(out.read_text("utf-8"))
    assert isinstance(rows, list)
    assert len(rows) == len(EXPECTED_ROWS)
    assert {(row["kind"], row["path"]) for row in rows} == EXPECTED_ROWS
    assert {row["kind"] for row in rows} == KINDS
    assert {row["status"] for row in rows} <= STATUSES
    words = [line.split() for line in result.stdout.splitlines()]
    table_lines = [line for line in words if line and line[0] in KINDS]
    assert len(table_lines) == len(rows)
    assert sorted(line[0] for line in table_lines) == sorted(row["kind"] for row in rows)
    over = [row for row in rows if (row["kind"], row["path"]) == OVER_ROW]
    assert len(over) == 1
    assert over[0]["status"] == "over"
    assert over[0]["budget"]["p95_ms"] == 0
