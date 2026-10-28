"""The perf CI gate (``scripts/perf/ci_gate.py``): reads ``perf.json`` and the budgets file, writes
a Markdown table to stdout and to ``$GITHUB_STEP_SUMMARY``, warns on an over row that is not
enforced, and fails only when an enforced row is over its budget plus the file's margin."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.perf.budgets import Budget
from scripts.perf.ci_gate import main
from scripts.perf.report import Row, write_rows

PROPOSED = "AGH-601 proposed"
MACHINE = {"platform": "linux", "cpus": 4}
SESSIONS = "/api/v1/sessions"
FEATURES_PAGE = "/features"
RESTART_API = "hub web start → /api/v1/sessions"
GUARD = "guard (PreToolUse Bash)"


def _row(
    kind: str,
    path: str,
    *,
    p95_ms: float | None,
    status: str,
    budget: Budget | None = None,
    api_calls: int | None = None,
    rss_mb: float | None = None,
    reason: str | None = None,
) -> Row:
    return Row(
        kind=kind,
        path=path,
        runs=10,
        median_ms=None if p95_ms is None else p95_ms / 2,
        p95_ms=p95_ms,
        budget=budget,
        status=status,
        reason=reason,
        api_calls=api_calls,
        rss_mb=rss_mb,
        events=400_000,
        seed=599,
        commit="0123abc",
        machine=MACHINE,
    )


def _perf(tmp_path: Path, rows: list[Row]) -> Path:
    path = tmp_path / "perf.json"
    write_rows(path, rows)
    assert [item["path"] for item in json.loads(path.read_text("utf-8"))] == [r.path for r in rows]
    return path


def _budgets(tmp_path: Path, entries: list[dict[str, object]], **top: object) -> Path:
    path = tmp_path / "budgets.json"
    path.write_text(json.dumps({"rows": entries, **top}), "utf-8")
    assert json.loads(path.read_text("utf-8"))["rows"] == entries
    return path


def _entry(kind: str, path: str, *, enforced: bool, **limits: float) -> dict[str, object]:
    return {"kind": kind, "path": path, **limits, "source": PROPOSED, "enforced": enforced}


def _argv(perf: Path, budgets: Path) -> list[str]:
    return ["--perf", str(perf), "--budgets", str(budgets)]


def _lines(text: str, prefix: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(prefix)]


@dataclass(frozen=True)
class OverCase:
    entry: Mapping[str, object]
    row: Row


# By hand, default margin 0.2: p95 150 ms -> 180 ms, 5 calls -> 6 calls, 300 MB -> 360 MB.
OVER_THE_MARGIN = [
    pytest.param(
        OverCase(
            _entry("route", SESSIONS, enforced=True, p95_ms=150),
            _row("route", SESSIONS, p95_ms=181.0, status="over"),
        ),
        id="p95",
    ),
    pytest.param(
        OverCase(
            _entry("page", FEATURES_PAGE, enforced=True, p95_ms=800, api_calls=5),
            _row("page", FEATURES_PAGE, p95_ms=400.0, api_calls=7, status="over"),
        ),
        id="api-calls",
    ),
    pytest.param(
        OverCase(
            _entry("restart", RESTART_API, enforced=True, p95_ms=1000, rss_mb=300),
            _row("restart", RESTART_API, p95_ms=900.0, rss_mb=361.0, status="over"),
        ),
        id="rss",
    ),
]


@pytest.mark.parametrize("case", OVER_THE_MARGIN)
def test_fails_naming_the_path_when_an_enforced_row_is_over_the_margin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: OverCase
) -> None:
    row = case.row
    passing = _row("hook", GUARD, p95_ms=40.0, status="pass")
    perf = _perf(tmp_path, [passing, row])
    budgets = _budgets(
        tmp_path, [_entry("hook", GUARD, enforced=True, p95_ms=80), dict(case.entry)]
    )

    code = main(_argv(perf, budgets), {})

    errors = _lines(capsys.readouterr().out, "::error")
    assert code == 1
    assert len(errors) == 1
    assert row.path in errors[0]
    assert GUARD not in errors[0]


@dataclass(frozen=True)
class MarginCase:
    top: Mapping[str, object]
    p95_ms: float
    expected: int


@pytest.mark.parametrize(
    "case",
    [
        # Default margin 0.2: 150 * 1.2 = 180, so 175 is within it.
        pytest.param(MarginCase({}, 175.0, 0), id="default-margin-within"),
        # File margin 0.5: 150 * 1.5 = 225, so 200 passes (it would fail the default 180).
        pytest.param(MarginCase({"margin": 0.5}, 200.0, 0), id="file-margin-within"),
        # File margin 0: the limit is the budget itself, so 151 fails.
        pytest.param(MarginCase({"margin": 0}, 151.0, 1), id="file-margin-zero"),
    ],
)
def test_judges_against_the_budget_plus_the_margin_when_an_enforced_row_is_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: MarginCase
) -> None:
    perf = _perf(tmp_path, [_row("route", SESSIONS, p95_ms=case.p95_ms, status="over")])
    entries = [_entry("route", SESSIONS, enforced=True, p95_ms=150)]
    budgets = _budgets(tmp_path, entries, **case.top)

    code = main(_argv(perf, budgets), {})

    errors = _lines(capsys.readouterr().out, "::error")
    assert code == case.expected
    assert len(errors) == case.expected


def test_passes_with_one_warning_naming_the_path_when_a_row_not_enforced_is_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 400 ms is far over 150 * 1.2 = 180: only the enforced flag keeps the job green.
    over = _row("route", SESSIONS, p95_ms=400.0, status="over")
    passing = _row("hook", GUARD, p95_ms=40.0, status="pass")
    perf = _perf(tmp_path, [passing, over])
    budgets = _budgets(
        tmp_path,
        [
            _entry("hook", GUARD, enforced=False, p95_ms=80),
            _entry("route", SESSIONS, enforced=False, p95_ms=150),
        ],
    )

    code = main(_argv(perf, budgets), {})

    out = capsys.readouterr().out
    warnings = _lines(out, "::warning")
    assert code == 0
    assert _lines(out, "::error") == []
    assert len(warnings) == 1
    assert SESSIONS in warnings[0]


def test_never_fails_when_rows_are_skipped_or_have_no_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skipped = _row("page", FEATURES_PAGE, p95_ms=None, status="skipped", reason="no Chromium")
    unbudgeted = _row(
        "cli", "./hub --version (local uvx stand-in)", p95_ms=99_000.0, status="no budget"
    )
    perf = _perf(tmp_path, [skipped, unbudgeted])
    budgets = _budgets(
        tmp_path, [_entry("page", FEATURES_PAGE, enforced=True, p95_ms=800, api_calls=5)]
    )

    code = main(_argv(perf, budgets), {})

    out = capsys.readouterr().out
    assert code == 0
    assert _lines(out, "::error") == []
    assert _lines(out, "::warning") == []


def _table_rows() -> list[Row]:
    return [
        _row("hook", GUARD, p95_ms=40.0, status="pass"),
        _row("route", SESSIONS, p95_ms=120.0, status="pass"),
        _row("page", FEATURES_PAGE, p95_ms=None, status="skipped", reason="no Chromium"),
    ]


def _table_budgets(tmp_path: Path) -> Path:
    return _budgets(
        tmp_path,
        [
            _entry("hook", GUARD, enforced=False, p95_ms=80),
            _entry("route", SESSIONS, enforced=False, p95_ms=150),
            _entry("page", FEATURES_PAGE, enforced=False, p95_ms=800, api_calls=5),
        ],
    )


def test_prints_one_markdown_line_per_row_when_the_gate_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = _table_rows()
    perf = _perf(tmp_path, rows)

    code = main(_argv(perf, _table_budgets(tmp_path)), {})

    table = _lines(capsys.readouterr().out, "|")
    assert code == 0
    # A header, the Markdown rule, then one line per perf.json row.
    assert len(table) == 2 + len(rows)
    header = [cell.strip() for cell in table[0].strip().strip("|").split("|")]
    assert len(header) == 10
    assert "enforced" in header
    for row in rows:
        assert len([line for line in table[2:] if row.path in line]) == 1
    # The route's margin-adjusted limit, by hand: 150 * 1.2 = 180.
    (sessions_line,) = [line for line in table[2:] if SESSIONS in line]
    assert "180" in sessions_line


def test_appends_the_table_to_the_step_summary_when_the_variable_is_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = _table_rows()
    perf = _perf(tmp_path, rows)
    summary = tmp_path / "step-summary.md"
    summary.write_text("## earlier step\n", "utf-8")
    assert summary.read_text("utf-8") == "## earlier step\n"

    code = main(_argv(perf, _table_budgets(tmp_path)), {"GITHUB_STEP_SUMMARY": str(summary)})

    text = summary.read_text("utf-8")
    table = _lines(text, "|")
    assert code == 0
    assert text.startswith("## earlier step\n")
    assert len(table) == 2 + len(rows)
    assert table == _lines(capsys.readouterr().out, "|")
