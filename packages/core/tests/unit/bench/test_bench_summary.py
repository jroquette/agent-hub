import pytest

from agent_hub.core.bench.bench_summary import (
    NO_CASES_TO_RUN,
    NOTHING_TO_VALIDATE,
    is_expected,
    summary,
    validate_line,
)
from agent_hub.core.json_form import JsonValue

# The hub characterization golden run_two_arms's summary, after its twelve records.
TWO_ARMS = """runs: 12, spent $4.50

| case | arm | pass | pass^k | cost | avg s |
|---|---|---|---|---|---|
| T1 | with | 1/3 | no | $1.50 | 0 |
| T1 | without | 0/3 | no | $0.75 | 0 |
| T2 | with | 3/3 | yes | $1.50 | 0 |
| T2 | without | 0/3 | no | $0.75 | 0 |

- **with**: pass@1 67%, pass^k 1/2, cost $3.00
- **without**: pass@1 0%, pass^k 0/2, cost $1.50"""
TAIL = "t fix missing mode=1 setup cfg=tttt staged=2 args: a/__main__.py t/__main__.py"


def a_record(case: str, arm: str, run: int, *, passed: bool) -> dict[str, JsonValue]:
    cost = 0.5 if arm == "with" else 0.25
    return {"case": case, "arm": arm, "run": run, "cost": cost, "secs": 0, "pass": passed}


def two_arms_records() -> list[dict[str, JsonValue]]:
    # The golden's job order: T2 before T1, `without` before `with`; T1-with passes in run 1 only.
    return [
        a_record(case, arm, run, passed=arm == "with" and (case == "T2" or run == 1))
        for run in (1, 2, 3)
        for case in ("T2", "T1")
        for arm in ("without", "with")
    ]


def test_pins_texts_when_module_loaded() -> None:
    assert NOTHING_TO_VALIDATE == (
        "no bench cases in brain/workflow/bench/tasks.json: nothing to validate"
    )
    assert NO_CASES_TO_RUN == (
        "no bench cases to run (brain/workflow/bench/tasks.json is empty or --cases matched none)"
    )


def test_prints_table_and_arms_when_records_given() -> None:
    assert summary(two_arms_records(), spent=4.5) == TWO_ARMS


def test_prints_empty_table_when_no_record() -> None:
    # The golden run_budget_stop_from_hub_worktree: the first wave already stops.
    expected = (
        "runs: 0, spent $0.00\n\n| case | arm | pass | pass^k | cost | avg s |\n"
        "|---|---|---|---|---|---|\n"
    )

    assert summary([], spent=0.0) == expected


def test_averages_seconds_and_counts_missing_cost_when_records_vary() -> None:
    # A timed-out run has no turns; a run whose tests could not be applied has no rc fields.
    records: list[dict[str, JsonValue]] = [
        {"case": "T1", "arm": "with", "cost": 0.135, "secs": 1800, "pass": False},
        {"case": "T1", "arm": "with", "cost": None, "secs": 5, "pass": True},
    ]

    text = summary(records, spent=0.135)

    assert "| T1 | with | 1/2 | no | $0.14 | 902 |" in text.splitlines()
    assert text.endswith("- **with**: pass@1 50%, pass^k 0/1, cost $0.14")


@pytest.mark.parametrize(
    ("label", "passed", "expected"),
    [
        ("parent", False, f"T1 parent pass=False OK {TAIL} "),
        ("parent", True, f"T1 parent pass=True MISMATCH {TAIL} "),
        ("merge", True, f"T1 merge  pass=True OK {TAIL} "),
        ("merge", False, f"T1 merge  pass=False MISMATCH {TAIL} "),
    ],
)
def test_formats_validate_line_when_grade_given(label: str, *, passed: bool, expected: str) -> None:
    grade: dict[str, JsonValue] = {"pass": passed, "hidden_rc": 0, "hidden_tail": TAIL}

    assert is_expected(label=label, grade=grade) is expected.endswith(f"OK {TAIL} ")
    assert validate_line(case_id="T1", label=label, grade=grade) == expected


def test_formats_validate_line_when_tests_not_applied() -> None:
    grade: dict[str, JsonValue] = {"pass": False, "error": "apply-tests: bad"}

    # No tail: two spaces, then the error, as the script printed it.
    assert validate_line(case_id="T1", label="merge", grade=grade) == (
        "T1 merge  pass=False MISMATCH  apply-tests: bad"
    )
