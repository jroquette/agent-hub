"""``make perf``'s budgets: read from ``budgets.json``, keyed by ``(kind, path)``.

The file is ``{"margin"?, "rows": [{"kind", "path", "p95_ms"?, "api_calls"?, "rss_mb"?, "source",
"enforced"?}]}``. Every load reads the file again, so an edit shows on the next run. ``enforced``
(default false) makes the CI gate (``ci_gate.py``) fail when the row is over; ``margin`` (a
fraction, default 0.2) widens only the gate's comparison for runner noise, never the stored budget.
Unknown fields, in an entry or at the top level, are ignored, so new fields can be added without
breaking a run. A path with no entry has no budget. A file that is not valid JSON, or an entry
without a string ``kind``, ``path`` and ``source``, with a non-numeric limit or a non-boolean
``enforced``, or a ``margin`` that is not a number of 0 or more, raises ``BudgetFileError`` naming
the file.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class BudgetFileError(Exception):
    """The budgets file cannot be read or does not have the expected shape."""


@dataclass(frozen=True)
class Budget:
    """One row's limits; ``None`` means that limit is not judged."""

    p95_ms: float | None
    api_calls: int | None
    rss_mb: float | None
    source: str
    enforced: bool = False


DEFAULT_MARGIN = 0.2


def load_budgets(path: Path) -> Mapping[tuple[str, str], Budget]:
    """Read ``path`` and return its budgets by ``(kind, path)``."""
    _, rows = _read(path)
    budgets: dict[tuple[str, str], Budget] = {}
    for index, entry in enumerate(rows):
        key, budget = _entry(path, index, entry)
        if key in budgets:
            raise BudgetFileError(f"{path}: rows[{index}] repeats {key[0]} {key[1]!r}")
        budgets[key] = budget
    return budgets


def load_margin(path: Path) -> float:
    """Read ``path``'s ``margin``: the fraction the CI gate adds to each budget, default 0.2."""
    data, _ = _read(path)
    if "margin" not in data:
        return DEFAULT_MARGIN
    margin = data["margin"]
    if isinstance(margin, bool) or not isinstance(margin, int | float) or margin < 0:
        raise BudgetFileError(f'{path}: "margin" must be a number of 0 or more')
    return float(margin)


def _read(path: Path) -> tuple[Mapping[str, object], list[object]]:
    try:
        data: object = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BudgetFileError(f"{path}: cannot read the budgets file: {error}") from error
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(rows, list):
        raise BudgetFileError(f'{path}: expected an object with a "rows" list')
    return data, rows


def _entry(path: Path, index: int, entry: object) -> tuple[tuple[str, str], Budget]:
    where = f"{path}: rows[{index}]"
    if not isinstance(entry, dict):
        raise BudgetFileError(f"{where} is not an object")
    texts = [entry.get(name) for name in ("kind", "path", "source")]
    kind, row_path, source = texts
    if not (isinstance(kind, str) and isinstance(row_path, str) and isinstance(source, str)):
        raise BudgetFileError(f'{where} needs string "kind", "path" and "source"')
    api_calls = _number(where, entry, "api_calls")
    if api_calls is not None and not isinstance(api_calls, int):
        raise BudgetFileError(f'{where}: "api_calls" must be a whole number')
    enforced = entry.get("enforced", False)
    if not isinstance(enforced, bool):
        raise BudgetFileError(f'{where}: "enforced" must be true or false')
    return (kind, row_path), Budget(
        p95_ms=_number(where, entry, "p95_ms"),
        api_calls=api_calls,
        rss_mb=_number(where, entry, "rss_mb"),
        source=source,
        enforced=enforced,
    )


def _number(where: str, entry: Mapping[str, object], name: str) -> float | None:
    value = entry.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BudgetFileError(f'{where}: "{name}" must be a number')
    return value
