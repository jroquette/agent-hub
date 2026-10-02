from typing import Any

from agent_hub.core.bench.bench_cases import BenchCase
from agent_hub.core.bench.bench_plan import ARMS, Job, jobs, run_cases, stop_line, waves

SHA = "0123456789abcdef0123456789abcdef01234567"


def a_case(case_id: str, **changes: Any) -> BenchCase:
    fields: dict[str, Any] = {
        "id": case_id,
        "repo": "api",
        "merge": SHA,
        "prompt": "Add the fix",
        "hidden_tests": ("t/__main__.py",),
        "test_cmd": ("python3",),
    }
    fields.update(changes)
    return BenchCase(**fields)


def shapes(built: tuple[Job, ...]) -> list[tuple[int, str, str]]:
    return [(job.run, job.case.id, job.arm) for job in built]


def test_pins_arms_when_module_loaded() -> None:
    assert ARMS == ("with", "without")


def test_interleaves_arms_when_jobs_built() -> None:
    cases = (a_case("T2"), a_case("T1"))

    built = jobs(cases, arms=("without", "with"), runs=2)

    # Run-major, then case, then arm, each in the order given: the script's job list.
    assert shapes(built) == [
        (1, "T2", "without"),
        (1, "T2", "with"),
        (1, "T1", "without"),
        (1, "T1", "with"),
        (2, "T2", "without"),
        (2, "T2", "with"),
        (2, "T1", "without"),
        (2, "T1", "with"),
    ]


def test_cuts_waves_when_parallel_given() -> None:
    built = jobs((a_case("T1"),), arms=ARMS, runs=5)

    cut = waves(built, parallel=3)

    assert [len(wave) for wave in cut] == [3, 3, 3, 1]
    assert tuple(job for wave in cut for job in wave) == built
    assert waves((), parallel=3) == ()


def test_stops_when_next_wave_exceeds_budget() -> None:
    # 0.165 + 0.135 is 0.30000000000000004 in floats: the script's sum, so the wave stops.
    line = stop_line(spent=0.165, wave=1, per_run=0.135, budget=0.3)

    assert line == "STOP: budget cap (spent $0.17, next wave up to $0.14)"
    assert stop_line(spent=0.0, wave=2, per_run=2.0, budget=1.0) == (
        "STOP: budget cap (spent $0.00, next wave up to $4.00)"
    )


def test_runs_wave_when_budget_exactly_reached() -> None:
    assert stop_line(spent=4.0, wave=1, per_run=1.0, budget=5.0) is None
    assert stop_line(spent=0.0, wave=3, per_run=2.0, budget=15.0) is None


def test_drops_excluded_and_unnamed_cases_when_selected() -> None:
    cases = (a_case("T1"), a_case("T10"), a_case("T2", excluded=True), a_case("T3"))

    assert [case.id for case in run_cases(cases, ids=())] == ["T1", "T10", "T3"]
    # Ids match whole: `T1` does not pick `T10`; an excluded case is never picked.
    assert [case.id for case in run_cases(cases, ids=("T3", "T1", "T2"))] == ["T1", "T3"]
    assert run_cases(cases, ids=("T",)) == ()
