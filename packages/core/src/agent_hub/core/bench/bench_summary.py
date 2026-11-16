"""What ``hub bench`` prints: the run's summary, ``--validate``'s lines and the no-case lines.

The hub script's texts, byte for byte: per case and arm the passes, whether every run passed
(pass^k), the cost and the mean seconds; per arm pass@1, pass^k and the cost. A record is the
JSON ``bench_session.run_record`` builds; a missing or non-numeric cost or time counts as 0.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from agent_hub.core.bench.bench_cases import TASKS_PATH
from agent_hub.core.json_form import JsonValue

type Record = Mapping[str, JsonValue]

NOTHING_TO_VALIDATE: Final = f"no bench cases in {TASKS_PATH}: nothing to validate"
NO_CASES_TO_RUN: Final = f"no bench cases to run ({TASKS_PATH} is empty or --cases matched none)"
_HEADER: Final = (
    "| case | arm | pass | pass^k | cost | avg s |",
    "|---|---|---|---|---|---|",
)


def summary(records: Sequence[Record], *, spent: float) -> str:
    """The table per case and arm, then one line per arm; both sorted."""
    lines = [f"runs: {len(records)}, spent ${spent:.2f}", "", *_HEADER]
    for case, arm in sorted({(_text(record, "case"), _text(record, "arm")) for record in records}):
        lines.append(_case_row(case, arm, [r for r in records if _key(r) == (case, arm)]))
    lines.append("")
    for arm in sorted({_text(record, "arm") for record in records}):
        lines.append(_arm_line(arm, [record for record in records if _text(record, "arm") == arm]))
    return "\n".join(lines)


def is_expected(*, label: str, grade: Record) -> bool:
    """Whether a grade is right: a fail on the parent, a pass on the merge."""
    return _passed(grade) == (label == "merge")


def validate_line(*, case_id: str, label: str, grade: Record) -> str:
    """``--validate``'s line for a case at ``label`` (``parent`` or ``merge``)."""
    verdict = "OK" if is_expected(label=label, grade=grade) else "MISMATCH"
    tail, error = grade.get("hidden_tail", ""), grade.get("error", "")
    return f"{case_id} {label:6} pass={_passed(grade)} {verdict} {tail} {error}"


def _case_row(case: str, arm: str, runs: Sequence[Record]) -> str:
    passes = sum(_passed(record) for record in runs)
    every = "yes" if passes == len(runs) else "no"
    seconds = sum(_number(record, "secs") for record in runs) // max(len(runs), 1)
    return f"| {case} | {arm} | {passes}/{len(runs)} | {every} | ${_cost(runs):.2f} | {seconds} |"


def _arm_line(arm: str, runs: Sequence[Record]) -> str:
    cases = sorted({_text(record, "case") for record in runs})
    every = sum(
        all(_passed(record) for record in runs if _text(record, "case") == case) for case in cases
    )
    pass_at_one = sum(_passed(record) for record in runs) / max(len(runs), 1)
    return (
        f"- **{arm}**: pass@1 {pass_at_one:.0%}, pass^k {every}/{len(cases)}, "
        f"cost ${_cost(runs):.2f}"
    )


def _cost(runs: Sequence[Record]) -> int | float:
    return sum(_number(record, "cost") for record in runs)


def _key(record: Record) -> tuple[str, str]:
    return _text(record, "case"), _text(record, "arm")


def _text(record: Record, key: str) -> str:
    return str(record.get(key))


def _passed(record: Record) -> bool:
    return record.get("pass") is True


def _number(record: Record, key: str) -> int | float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return value
