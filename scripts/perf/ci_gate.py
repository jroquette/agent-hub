"""The perf CI gate: ``python -m scripts.perf.ci_gate [--perf perf.json] [--budgets budgets.json]``.

It reads the runner's ``perf.json`` (``report.write_rows``) and the budgets file, judges each row
again against its budget, and prints a Markdown table (also appended to ``$GITHUB_STEP_SUMMARY``
when that is set). A row over its budget prints a GitHub ``::warning::`` line naming the path. A
row whose entry is ``enforced`` and whose p95, API call count or peak RSS is strictly above the
budget times ``1 + margin`` prints an ``::error::`` line instead, and the gate exits 1. Skipped
and no-budget rows never fail; an enforced row that was skipped warns. An unreadable or wrongly
typed ``perf.json``, a bad budgets file, or a step summary that cannot be written exits 2.
"""

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from scripts.perf.budgets import Budget, BudgetFileError, load_budgets, load_margin
from scripts.perf.report import OVER, SKIPPED, Row, status_of

REPO_ROOT = Path(__file__).resolve().parents[2]

HEADER = (
    "kind",
    "path",
    "runs",
    "median ms",
    "p95 ms",
    "calls / MB",
    "budget",
    "limit (+margin)",
    "status",
    "enforced",
)


class PerfFileError(Exception):
    """``perf.json`` cannot be read or does not have the runner's shape."""


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """0 when no enforced row is over its budget plus the margin, 1 when one is, 2 on bad input."""
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        budgets = load_budgets(args.budgets)
        margin = load_margin(args.budgets)
        judged, table = _judge_all(args.perf, read_rows(args.perf), budgets=budgets, margin=margin)
    except (BudgetFileError, PerfFileError) as error:
        print(f"::error::perf gate: {error}")
        return 2
    print(table, end="")
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with Path(summary).open("a", encoding="utf-8") as file:
                file.write(f"### Perf budgets (margin {margin:.0%})\n\n{table}\n")
        except OSError as error:
            print(f"::error::perf gate: cannot append to {summary}: {error}")
            return 2
    failed = False
    for row in judged:
        if row.status == SKIPPED and row.budget is not None and row.budget.enforced:
            # Once a budget is enforced, a run that stops measuring it must not stay silent.
            print(f"::warning::perf: {row.kind} {row.path} is enforced but was skipped")
            continue
        if row.status != OVER or row.budget is None:
            continue
        over = _over_limit(row, row.budget, margin)
        if row.budget.enforced and over:
            failed = True
            print(f"::error::perf: {row.kind} {row.path} is over its enforced budget: {over}")
        else:
            why = "within the margin" if row.budget.enforced else "not enforced"
            print(f"::warning::perf: {row.kind} {row.path} is over its budget ({why})")
    return 1 if failed else 0


def read_rows(path: Path) -> list[Row]:
    """The rows of ``path``, a ``perf.json`` as ``report.write_rows`` writes it."""
    try:
        items: object = json.loads(path.read_text("utf-8"))
        if not isinstance(items, list):
            raise PerfFileError(f"{path}: expected a JSON list of rows")
        return [_row(item) for item in items]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PerfFileError(f"{path}: cannot read perf.json: {error}") from error
    except (KeyError, TypeError) as error:
        raise PerfFileError(f"{path}: a row does not have the runner's fields: {error}") from error


def table_markdown(rows: Sequence[Row], margin: float) -> str:
    """A header, the Markdown rule, then one line per row."""
    lines = [HEADER, tuple("---" for _ in HEADER), *(_cells(row, margin) for row in rows)]
    return "".join("| " + " | ".join(_escape(cell) for cell in line) + " |\n" for line in lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.perf.ci_gate")
    parser.add_argument("--perf", type=Path, default=REPO_ROOT / "perf.json")
    parser.add_argument(
        "--budgets", type=Path, default=REPO_ROOT / "scripts" / "perf" / "budgets.json"
    )
    return parser


def _row(item: object) -> Row:
    if not isinstance(item, dict):
        raise TypeError("a row is not an object")
    # The budget is read again from the budgets file, so perf.json's copy is dropped.
    return Row(**{**item, "budget": None})


def _judge_all(
    path: Path, rows: Sequence[Row], *, budgets: Mapping[tuple[str, str], Budget], margin: float
) -> tuple[list[Row], str]:
    """The judged rows and their table; a field of the wrong type raises ``PerfFileError``."""
    try:
        judged = [_judge(row, budgets.get((row.kind, row.path))) for row in rows]
        return judged, table_markdown(judged, margin)
    except (TypeError, ValueError) as error:
        raise PerfFileError(f"{path}: a row has a field of the wrong type: {error}") from error


def _judge(row: Row, budget: Budget | None) -> Row:
    """``row`` with ``budget`` and its status against it; a skipped row stays skipped."""
    return replace(row, budget=budget, status=status_of(row, budget))


def _limits(budget: Budget, margin: float) -> tuple[float | None, float | None, float | None]:
    def widen(limit: float | None) -> float | None:
        return None if limit is None else limit * (1 + margin)

    return widen(budget.p95_ms), widen(budget.api_calls), widen(budget.rss_mb)


def _over_limit(row: Row, budget: Budget, margin: float) -> str:
    """What is over ``budget`` plus ``margin``, as text; empty when nothing is."""
    p95, calls, rss = _limits(budget, margin)
    checks = (
        (row.p95_ms, p95, "p95 {value} ms > {limit} ms"),
        (row.api_calls, calls, "{value} API calls > {limit}"),
        (row.rss_mb, rss, "peak RSS {value} MB > {limit} MB"),
    )
    found = [
        text.format(value=_amount(value), limit=_amount(limit))
        for value, limit, text in checks
        if value is not None and limit is not None and value > limit
    ]
    return ", ".join(found)


def _cells(row: Row, margin: float) -> tuple[str, ...]:
    status = f"{row.status}: {row.reason}" if row.reason else row.status
    extra = _amount(row.api_calls) if row.api_calls is not None else _amount(row.rss_mb)
    budget = row.budget
    return (
        row.kind,
        row.path,
        str(row.runs),
        _amount(row.median_ms),
        _amount(row.p95_ms),
        extra,
        "-" if budget is None else _budget_text(budget.p95_ms, budget.api_calls, budget.rss_mb),
        "-" if budget is None else _budget_text(*_limits(budget, margin)),
        status,
        "yes" if budget is not None and budget.enforced else "no",
    )


def _budget_text(p95_ms: float | None, calls: float | None, rss_mb: float | None) -> str:
    parts = []
    if p95_ms is not None:
        parts.append(f"{_amount(p95_ms)} ms")
    if calls is not None:
        parts.append(f"{_amount(calls)} calls")
    if rss_mb is not None:
        parts.append(f"{_amount(rss_mb)} MB")
    return " / ".join(parts) or "-"


def _amount(value: float | None) -> str:
    """One decimal place without a trailing ``.0``, so a widened limit of 3.6 never reads as 4."""
    return "-" if value is None else f"{value:.1f}".removesuffix(".0")


def _escape(cell: str) -> str:
    return cell.replace("|", "\\|")


if __name__ == "__main__":
    sys.exit(main())
