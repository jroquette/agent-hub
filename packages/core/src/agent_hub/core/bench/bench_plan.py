"""The plan of a bench run: which cases, the jobs in order, their waves and the budget stop.

The order and the stop are the hub script's: jobs run-major, then case, then arm, so both arms
see the same drift; a wave starts only while ``spent + len(wave) * per_run <= budget``, summed in
floats as the script summed them, so the total stays within the budget.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Final

from agent_hub.core.bench.bench_cases import BenchCase

ARMS: Final = ("with", "without")


@dataclass(frozen=True, kw_only=True, slots=True)
class Job:
    """One run of one case in one arm; ``run`` counts from 1."""

    case: BenchCase
    arm: str
    run: int


def run_cases(cases: Sequence[BenchCase], *, ids: Collection[str]) -> tuple[BenchCase, ...]:
    """The cases a run takes, in file order: never an excluded one; those ``ids`` names if any.

    An id matches whole (``T1`` never picks ``T10``).
    """
    return tuple(case for case in cases if not case.excluded and (not ids or case.id in ids))


def jobs(cases: Sequence[BenchCase], *, arms: Sequence[str], runs: int) -> tuple[Job, ...]:
    """Every job: for each run, each case, each arm, in the order given."""
    return tuple(
        Job(case=case, arm=arm, run=run)
        for run in range(1, runs + 1)
        for case in cases
        for arm in arms
    )


def waves(planned: Sequence[Job], *, parallel: int) -> tuple[tuple[Job, ...], ...]:
    """``planned`` cut into consecutive waves of ``parallel`` jobs; the last may be shorter."""
    return tuple(
        tuple(planned[start : start + parallel]) for start in range(0, len(planned), parallel)
    )


def stop_line(*, spent: float, wave: int, per_run: float, budget: float) -> str | None:
    """The script's ``STOP:`` line when a wave of ``wave`` jobs could exceed ``budget``."""
    next_wave = wave * per_run
    if spent + next_wave <= budget:
        return None
    return f"STOP: budget cap (spent ${spent:.2f}, next wave up to ${next_wave:.2f})"
