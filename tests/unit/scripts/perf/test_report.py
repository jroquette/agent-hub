"""The perf report (``scripts/perf/report.py``): median and p95 of the samples, each row's status
against its budget, the printed table, ``perf.json`` and the exit code (spec AC-1, AC-3, AC-4)."""

import json
from pathlib import Path

import pytest

from scripts.perf.budgets import Budget
from scripts.perf.report import Row, exit_code, status_of, summarize, table_text, write_rows

PROPOSED = "AGH-601 proposed"
MACHINE = {"platform": "linux", "cpus": 4}
ROW_FIELDS = {
    "kind",
    "path",
    "runs",
    "median_ms",
    "p95_ms",
    "budget",
    "status",
    "events",
    "seed",
    "commit",
    "machine",
}


def _budget(
    p95_ms: int | None = None, api_calls: int | None = None, rss_mb: int | None = None
) -> Budget:
    return Budget(p95_ms=p95_ms, api_calls=api_calls, rss_mb=rss_mb, source=PROPOSED)


def _row(
    kind: str = "route",
    path: str = "/api/v1/sessions",
    *,
    runs: int = 10,
    median_ms: float | None = 40.0,
    p95_ms: float | None = 60.0,
    budget: Budget | None = None,
    status: str = "pass",
    reason: str | None = None,
    api_calls: int | None = None,
    rss_mb: float | None = None,
) -> Row:
    return Row(
        kind=kind,
        path=path,
        runs=runs,
        median_ms=median_ms,
        p95_ms=p95_ms,
        budget=budget,
        status=status,
        reason=reason,
        api_calls=api_calls,
        rss_mb=rss_mb,
        events=2_000,
        seed=599,
        commit="0123abc",
        machine=MACHINE,
    )


def test_takes_the_value_itself_when_one_run() -> None:
    assert tuple(summarize([42.5])) == (42.5, 42.5)


def test_matches_inclusive_quantiles_when_ten_runs() -> None:
    # By hand: sorted 10..100; median (50 + 60) / 2 = 55; inclusive p95 sits at 9 * 19/20 = 8.55,
    # so 90 + 0.55 * (100 - 90) = 95.5.
    median, p95 = summarize([30.0, 10.0, 100.0, 20.0, 50.0, 40.0, 70.0, 60.0, 90.0, 80.0])

    assert median == pytest.approx(55.0)
    assert p95 == pytest.approx(95.5)


@pytest.mark.parametrize(
    ("p95_ms", "expected"),
    [(151.0, "over"), (150.0, "pass"), (149.0, "pass")],
)
def test_marks_over_when_p95_exceeds_the_budget(p95_ms: float, expected: str) -> None:
    row = _row(p95_ms=p95_ms, median_ms=100.0)

    assert status_of(row, _budget(p95_ms=150)) == expected


@pytest.mark.parametrize(("api_calls", "expected"), [(6, "over"), (5, "pass")])
def test_marks_over_when_api_calls_exceed_the_budget(api_calls: int, expected: str) -> None:
    row = _row("page", "/features", median_ms=300.0, p95_ms=400.0, api_calls=api_calls)

    assert status_of(row, _budget(p95_ms=800, api_calls=5)) == expected


@pytest.mark.parametrize(("rss_mb", "expected"), [(301.0, "over"), (300.0, "pass")])
def test_marks_over_when_rss_exceeds_the_budget(rss_mb: float, expected: str) -> None:
    row = _row(
        "restart",
        "hub web start → /api/v1/sessions",
        runs=3,
        median_ms=700.0,
        p95_ms=900.0,
        rss_mb=rss_mb,
    )

    assert status_of(row, _budget(p95_ms=1000, rss_mb=300)) == expected


def test_ignores_the_rss_budget_when_rss_is_unknown() -> None:
    row = _row("restart", "hub web start → GET /", runs=3, median_ms=700.0, p95_ms=900.0)
    assert row.rss_mb is None

    assert status_of(row, _budget(p95_ms=1000, rss_mb=300)) == "pass"


def test_marks_no_budget_when_the_entry_is_missing() -> None:
    row = _row(median_ms=9_000.0, p95_ms=99_000.0)

    assert status_of(row, None) == "no budget"


def test_keeps_skipped_when_the_row_was_skipped() -> None:
    row = _row(
        "page",
        "/features",
        runs=0,
        median_ms=None,
        p95_ms=None,
        status="skipped",
        reason="no Chromium found",
    )

    assert status_of(row, _budget(p95_ms=800, api_calls=5)) == "skipped"


def test_exits_zero_when_a_row_is_over_and_strict_is_off() -> None:
    rows = [_row(status="pass"), _row("hook", "session_end", status="over")]

    assert exit_code(rows, strict=False) == 0


def test_exits_one_when_a_row_is_over_and_strict_is_on() -> None:
    rows = [_row(status="pass"), _row("hook", "session_end", status="over")]

    assert exit_code(rows, strict=True) == 1


@pytest.mark.parametrize("strict", [True, False])
def test_exits_zero_when_every_row_passes_and_strict_is_on(strict: bool) -> None:  # noqa: FBT001
    rows = [_row(status="pass"), _row("hook", "session_end", status="pass")]

    assert exit_code(rows, strict=strict) == 0


def test_exits_zero_when_rows_are_skipped_or_unbudgeted_and_strict_is_on() -> None:
    rows = [
        _row(status="pass"),
        _row("route", "/api/v1/features", status="no budget"),
        _row("page", "/", runs=0, median_ms=None, p95_ms=None, status="skipped", reason="no npm"),
    ]

    assert exit_code(rows, strict=True) == 0


# One row of each kind, plus a skipped page; no path is a substring of another.
ROWS = [
    _row("cli", "hub --version", median_ms=101.0, p95_ms=133.0, budget=_budget(p95_ms=150)),
    _row(
        "hook",
        "guard (PreToolUse Bash)",
        median_ms=41.0,
        p95_ms=97.0,
        budget=_budget(p95_ms=80),
        status="over",
    ),
    _row("route", "/api/v1/search?q=make", median_ms=12.0, p95_ms=17.0, status="no budget"),
    _row(
        "page",
        "/features/perf/search-index",
        median_ms=640.0,
        p95_ms=710.0,
        api_calls=63,
        budget=_budget(p95_ms=800, api_calls=5),
        status="over",
    ),
    _row(
        "restart",
        "hub web start → GET /",
        runs=3,
        median_ms=2_010.0,
        p95_ms=2_090.0,
        rss_mb=412.0,
        budget=_budget(p95_ms=1000, rss_mb=300),
        status="over",
    ),
    _row(
        "page",
        "/sessions/perf-session",
        runs=0,
        median_ms=None,
        p95_ms=None,
        budget=_budget(p95_ms=800, api_calls=5),
        status="skipped",
        reason="no Chromium found",
    ),
]
# What each row's table line must show (AC-1): path, runs, median, p95, budget, status, plus the
# API call count for pages and RSS for restarts.
SHOWN = [
    ("hub --version", "10", "101", "133", "150", "pass"),
    ("guard (PreToolUse Bash)", "10", "41", "97", "80", "over"),
    ("/api/v1/search?q=make", "10", "12", "17", "no budget"),
    ("/features/perf/search-index", "10", "640", "710", "800", "63", "over"),
    ("hub web start → GET /", "3", "2010", "2090", "1000", "412", "300", "over"),
    ("/sessions/perf-session", "skipped", "no Chromium found"),
]


def _row_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if any(row.path in line for row in ROWS)]


def test_prints_one_table_line_per_row_when_rendered() -> None:
    lines = _row_lines(table_text(ROWS))

    assert len(lines) == len(ROWS) == len(SHOWN)
    for line, shown in zip(lines, SHOWN, strict=True):
        assert shown[0] in line
        assert [part for part in shown if part not in line.replace(",", "")] == [], line


def test_writes_the_same_rows_when_perf_json_is_written(tmp_path: Path) -> None:
    out = tmp_path / "perf.json"

    write_rows(out, ROWS)
    written = json.loads(out.read_text("utf-8"))

    assert isinstance(written, list)
    assert len(written) == len(_row_lines(table_text(ROWS))) == len(ROWS)
    assert [(item["kind"], item["path"], item["status"]) for item in written] == [
        (row.kind, row.path, row.status) for row in ROWS
    ]
    for item in written:
        assert set(item) >= ROW_FIELDS, item
        assert item["machine"] == MACHINE
        assert (item["events"], item["seed"], item["commit"]) == (2_000, 599, "0123abc")
    cli, _hook, route, page, restart, skipped = written
    assert (cli["runs"], cli["median_ms"], cli["p95_ms"]) == (10, 101.0, 133.0)
    assert cli["budget"]["p95_ms"] == 150
    assert route["budget"] is None
    assert page["api_calls"] == 63
    assert page["budget"]["api_calls"] == 5
    assert restart["rss_mb"] == 412.0
    assert restart["budget"]["rss_mb"] == 300
    assert skipped["reason"] == "no Chromium found"
