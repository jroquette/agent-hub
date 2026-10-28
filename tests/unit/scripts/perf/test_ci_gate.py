"""The perf CI gate (``scripts/perf/ci_gate.py``): reads ``perf.json`` and the budgets file, writes
a Markdown table to stdout and to ``$GITHUB_STEP_SUMMARY``, warns on an over row that is not
enforced, and fails only when an enforced row is over its budget plus the file's margin."""

import json
from collections.abc import Callable, Mapping
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


# AGH-602 (AC-2): an enforced budget over the margin fails the job and names the path.
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
    warns: bool


# AGH-602 (AC-2): the margin widens only the comparison; within it, the row warns, not fails.
@pytest.mark.parametrize(
    "case",
    [
        # Default margin 0.2: 150 * 1.2 = 180, so 175 is within it.
        pytest.param(MarginCase({}, 175.0, 0, warns=True), id="default-margin-within"),
        # Exactly at the limit (150 * 1.2 = 180) is not strictly above it, so it only warns.
        pytest.param(MarginCase({}, 180.0, 0, warns=True), id="default-margin-boundary"),
        # File margin 0.5: 150 * 1.5 = 225, so 200 passes (it would fail the default 180).
        pytest.param(MarginCase({"margin": 0.5}, 200.0, 0, warns=True), id="file-margin-within"),
        # File margin 0: the limit is the budget itself, so 151 fails.
        pytest.param(MarginCase({"margin": 0}, 151.0, 1, warns=False), id="file-margin-zero"),
    ],
)
def test_judges_against_the_budget_plus_the_margin_when_an_enforced_row_is_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: MarginCase
) -> None:
    perf = _perf(tmp_path, [_row("route", SESSIONS, p95_ms=case.p95_ms, status="over")])
    entries = [_entry("route", SESSIONS, enforced=True, p95_ms=150)]
    budgets = _budgets(tmp_path, entries, **case.top)

    code = main(_argv(perf, budgets), {})

    out = capsys.readouterr().out
    errors = _lines(out, "::error")
    warnings = _lines(out, "::warning")
    assert code == case.expected
    assert len(errors) == case.expected
    if case.warns:
        assert len(warnings) == 1
        assert SESSIONS in warnings[0]
        assert "within the margin" in warnings[0]
    else:
        assert warnings == []


# AGH-602 (AC-3): a budget not enforced only warns, however far over it is.
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


# AGH-602 (AC-2, AC-3): skipped and no-budget rows neither fail nor warn.
def test_never_fails_when_rows_are_skipped_or_have_no_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skipped = _row("page", FEATURES_PAGE, p95_ms=None, status="skipped", reason="no Chromium")
    unbudgeted = _row(
        "cli", "./hub --version (local uvx stand-in)", p95_ms=99_000.0, status="no budget"
    )
    perf = _perf(tmp_path, [skipped, unbudgeted])
    budgets = _budgets(
        tmp_path, [_entry("page", FEATURES_PAGE, enforced=False, p95_ms=800, api_calls=5)]
    )

    code = main(_argv(perf, budgets), {})

    out = capsys.readouterr().out
    assert code == 0
    assert _lines(out, "::error") == []
    assert _lines(out, "::warning") == []


# AGH-602 (AC-2): an enforced row that was skipped passes, but says so, so CI cannot stop
# measuring an enforced budget without a sign.
def test_passes_with_one_warning_naming_the_path_when_an_enforced_row_is_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skipped = _row("page", FEATURES_PAGE, p95_ms=None, status="skipped", reason="no Chromium")
    passing = _row("hook", GUARD, p95_ms=40.0, status="pass")
    perf = _perf(tmp_path, [passing, skipped])
    budgets = _budgets(
        tmp_path,
        [
            _entry("hook", GUARD, enforced=True, p95_ms=80),
            _entry("page", FEATURES_PAGE, enforced=True, p95_ms=800, api_calls=5),
        ],
    )

    code = main(_argv(perf, budgets), {})

    out = capsys.readouterr().out
    warnings = _lines(out, "::warning")
    assert code == 0
    assert _lines(out, "::error") == []
    assert len(warnings) == 1
    assert FEATURES_PAGE in warnings[0]
    assert "skipped" in warnings[0]


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


# AGH-602 (AC-1): the table the job posts has one line per perf.json row.
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


# AGH-602 (AC-1): the table goes to the job summary.
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


def _bad_perf_not_json(tmp_path: Path) -> Path:
    path = tmp_path / "perf.json"
    path.write_text("{not json", "utf-8")
    return path


def _bad_perf_not_a_list(tmp_path: Path) -> Path:
    path = tmp_path / "perf.json"
    path.write_text(json.dumps({"rows": []}), "utf-8")
    return path


def _bad_perf_unknown_field(tmp_path: Path) -> Path:
    path = _perf(tmp_path, [_row("route", SESSIONS, p95_ms=120.0, status="pass")])
    items = json.loads(path.read_text("utf-8"))
    items[0]["surprise"] = 1
    path.write_text(json.dumps(items), "utf-8")
    return path


def _bad_perf_missing(tmp_path: Path) -> Path:
    return tmp_path / "absent.json"


def _bad_perf_wrong_type(tmp_path: Path) -> Path:
    path = _perf(tmp_path, [_row("route", SESSIONS, p95_ms=120.0, status="pass")])
    items = json.loads(path.read_text("utf-8"))
    items[0]["p95_ms"] = "x"
    path.write_text(json.dumps(items), "utf-8")
    return path


@pytest.mark.parametrize(
    "make_perf",
    [
        pytest.param(_bad_perf_not_json, id="not-json"),
        pytest.param(_bad_perf_not_a_list, id="not-a-list"),
        pytest.param(_bad_perf_unknown_field, id="unknown-field"),
        pytest.param(_bad_perf_missing, id="missing"),
        pytest.param(_bad_perf_wrong_type, id="wrong-type"),
    ],
)
def test_exits_two_with_one_error_line_when_perf_json_is_bad(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_perf: Callable[[Path], Path]
) -> None:
    perf = make_perf(tmp_path)
    budgets = _budgets(tmp_path, [_entry("route", SESSIONS, enforced=True, p95_ms=150)])

    code = main(_argv(perf, budgets), {})

    errors = _lines(capsys.readouterr().out, "::error")
    assert code == 2
    assert len(errors) == 1
    assert errors[0].startswith("::error::perf gate:")
    assert str(perf) in errors[0]


@pytest.mark.parametrize(
    "top",
    [
        pytest.param({"margin": -0.1}, id="negative-margin"),
        pytest.param({"margin": True}, id="bool-margin"),
        pytest.param({"margin": "20%"}, id="text-margin"),
        pytest.param({"margin": float("nan")}, id="nan-margin"),
        pytest.param({"margin": float("inf")}, id="infinite-margin"),
    ],
)
def test_exits_two_with_one_error_line_when_the_budgets_file_is_bad(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], top: Mapping[str, object]
) -> None:
    perf = _perf(tmp_path, [_row("route", SESSIONS, p95_ms=120.0, status="pass")])
    budgets = _budgets(tmp_path, [_entry("route", SESSIONS, enforced=True, p95_ms=150)], **top)

    code = main(_argv(perf, budgets), {})

    errors = _lines(capsys.readouterr().out, "::error")
    assert code == 2
    assert len(errors) == 1
    assert errors[0].startswith("::error::perf gate:")
    assert "margin" in errors[0]


# AGH-602: a step summary that cannot be written is bad input, not an enforced budget over.
def test_exits_two_with_one_error_line_when_the_step_summary_cannot_be_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    perf = _perf(tmp_path, [_row("route", SESSIONS, p95_ms=120.0, status="pass")])
    budgets = _budgets(tmp_path, [_entry("route", SESSIONS, enforced=True, p95_ms=150)])
    # A directory cannot be opened for appending.
    summary = tmp_path / "summary-dir"
    summary.mkdir()

    code = main(_argv(perf, budgets), {"GITHUB_STEP_SUMMARY": str(summary)})

    errors = _lines(capsys.readouterr().out, "::error")
    assert code == 2
    assert len(errors) == 1
    assert errors[0].startswith("::error::perf gate:")
    assert str(summary) in errors[0]
