"""``make perf``'s report: one ``Row`` per measured path, its status, the table and ``perf.json``.

p95 is ``statistics.quantiles(n=20, method="inclusive")[-1]``, as in the API's NFR tests; with one
run it is the value itself. A row is ``over`` when its p95, API call count or peak RSS is strictly
above its budget; an unknown RSS (``None``, off Linux) is not judged. A row with no budget entry is
``no budget`` and a row that could not run stays ``skipped``. Neither fails ``PERF_STRICT=1``.
"""

import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NamedTuple

from scripts.perf.budgets import Budget

PASSED = "pass"
OVER = "over"
NO_BUDGET = "no budget"
SKIPPED = "skipped"


class Summary(NamedTuple):
    median_ms: float
    p95_ms: float


@dataclass(frozen=True)
class Row:
    """One ``perf.json`` item; ``reason`` is set for skipped rows only.

    ``dom_nodes`` is a page row's most elements in one run: written to ``perf.json`` only, with
    no budget and no table column; ``None`` on every other row."""

    kind: str
    path: str
    runs: int
    median_ms: float | None
    p95_ms: float | None
    budget: Budget | None
    status: str
    reason: str | None
    api_calls: int | None
    rss_mb: float | None
    events: int
    seed: int
    commit: str
    machine: Mapping[str, object]
    dom_nodes: int | None = None


def summarize(samples: Sequence[float]) -> Summary:
    """Median and inclusive p95 of ``samples`` (at least one)."""
    if len(samples) == 1:
        return Summary(samples[0], samples[0])
    p95 = statistics.quantiles(samples, n=20, method="inclusive")[-1]
    return Summary(statistics.median(samples), p95)


def status_of(row: Row, budget: Budget | None) -> str:
    """``row``'s status against ``budget``; a skipped row stays skipped."""
    if row.status == SKIPPED:
        return SKIPPED
    if budget is None:
        return NO_BUDGET
    checks = (
        (row.p95_ms, budget.p95_ms),
        (row.api_calls, budget.api_calls),
        (row.rss_mb, budget.rss_mb),
    )
    over = any(value is not None and limit is not None and value > limit for value, limit in checks)
    return OVER if over else PASSED


def exit_code(rows: Sequence[Row], *, strict: bool) -> int:
    """1 when ``strict`` and a row is over its budget, else 0."""
    return 1 if strict and any(row.status == OVER for row in rows) else 0


HEADER = ("kind", "path", "runs", "median ms", "p95 ms", "calls / MB", "budget", "status")


def table_text(rows: Sequence[Row]) -> str:
    """The printed table: a header, a rule, then one line per row."""
    lines = [HEADER, *(_cells(row) for row in rows)]
    widths = [max(len(line[column]) for line in lines) for column in range(len(HEADER))]
    rendered = [
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in lines
    ]
    rendered.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(rendered) + "\n"


def write_rows(path: Path, rows: Sequence[Row]) -> None:
    """Write ``rows`` to ``path`` as a JSON list, one object per row."""
    items = [asdict(row) for row in rows]
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _cells(row: Row) -> tuple[str, ...]:
    status = f"{row.status}: {row.reason}" if row.reason else row.status
    extra = _amount(row.api_calls) if row.api_calls is not None else _amount(row.rss_mb)
    return (
        row.kind,
        row.path,
        str(row.runs),
        _amount(row.median_ms),
        _amount(row.p95_ms),
        extra,
        _budget_text(row.budget),
        status,
    )


def _budget_text(budget: Budget | None) -> str:
    if budget is None:
        return "-"
    parts = []
    if budget.p95_ms is not None:
        parts.append(f"{_amount(budget.p95_ms)} ms")
    if budget.api_calls is not None:
        parts.append(f"{budget.api_calls} calls")
    if budget.rss_mb is not None:
        parts.append(f"{_amount(budget.rss_mb)} MB")
    return " / ".join(parts) or "-"


def _amount(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"
