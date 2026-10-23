"""The hub's skill and agent usage report: join, order and Markdown (AGH-482).

Pure functions over the usage fold's windows (``SkillUsage.windows_by_*``): one row per hub
item, 0 runs and no last use for an item with no event; names, counts and times only
(ADR 0019). The ordering puts the items never used in the chosen window first, then the most
run, then project, kind and name; the API, the CLI and the UI all use it.
"""

from collections.abc import Iterable
from typing import Final

from agent_hub.core.skills.skill_view import ItemKind, SkillUsage, UsageDays, UsageRow

NOT_READ_LINE: Final = "Some items were not read; the list may be incomplete."
_HEADER: Final = "| Project | Kind | Name | 7 d | 30 d | 90 d | Last used (UTC) |"
_RULE: Final = "| --- | --- | --- | --- | --- | --- | --- |"
_NEVER: Final = "never"


def usage_rows(
    project: str, items: Iterable[tuple[ItemKind, str]], usage: SkillUsage | None
) -> tuple[UsageRow, ...]:
    """One row per skill or agent of ``items`` (hooks are skipped), in the given order, with its
    windows from ``usage`` (zeros and no last use when it has none)."""
    rows: list[UsageRow] = []
    for kind, name in items:
        if kind is ItemKind.HOOK:
            continue
        windows = None
        if usage is not None:
            found = usage.windows_by_skill if kind is ItemKind.SKILL else usage.windows_by_agent
            windows = found.get(name)
        rows.append(
            UsageRow(
                project=project,
                kind=kind,
                name=name,
                runs_7d=0 if windows is None else windows.runs_7d,
                runs_30d=0 if windows is None else windows.runs_30d,
                runs_90d=0 if windows is None else windows.runs_90d,
                last_used_at=None if windows is None else windows.last_used_at,
            )
        )
    return tuple(rows)


def runs_in(row: UsageRow, days: UsageDays) -> int:
    """The row's runs over ``days``."""
    match days:
        case 7:
            return row.runs_7d
        case 30:
            return row.runs_30d
        case 90:
            return row.runs_90d


def ordered_usage(rows: Iterable[UsageRow], days: UsageDays) -> tuple[UsageRow, ...]:
    """``rows`` with the ones never run in ``days`` first, then by runs descending, then by
    project, kind and name."""
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                runs_in(row, days) != 0,
                -runs_in(row, days),
                row.project,
                row.kind.value,
                row.name,
            ),
        )
    )


def _cell_name(row: UsageRow) -> str:
    return f"/{row.name}" if row.kind is ItemKind.SKILL else row.name


def _last_used(row: UsageRow) -> str:
    return _NEVER if row.last_used_at is None else row.last_used_at.date().isoformat()


def usage_markdown(rows: Iterable[UsageRow], *, days: UsageDays, truncated: bool) -> str:
    """A Markdown table of ``rows`` (as given) under a line naming the window; a ``truncated``
    report ends with the not-read line. Names match ``ITEM_NAME``, so nothing is escaped."""
    lines = [f"Skills and agents: runs in the last {days} days, never used first.", "", _HEADER]
    lines.append(_RULE)
    lines.extend(
        f"| {row.project} | {row.kind.value} | {_cell_name(row)} | {row.runs_7d} | "
        f"{row.runs_30d} | {row.runs_90d} | {_last_used(row)} |"
        for row in rows
    )
    if truncated:
        lines.extend(["", NOT_READ_LINE])
    return "\n".join(lines) + "\n"
