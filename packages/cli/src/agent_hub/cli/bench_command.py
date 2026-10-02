"""``hub bench``: the configuration benchmark of the ``bench`` module (spec D2, Q-3).

The hub is ``AGENT_HUB_ROOT`` or the cwd; its ``hub.json`` must select ``bench``. Usage problems
exit 2 before any read of the cases or any child process: an option out of its bound,
``--validate`` with a run option, ``BENCH_EFFORT`` (the sessions' ``effortLevel``; unset or
empty is ``medium``) other than ``low``, ``medium`` or ``high``, a folder that is not a hub, a
hub without ``bench``. An invalid ``hub.json`` exits 1 with the reader's lines.
"""

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Final

import typer
from typer._click.core import ParameterSource

from agent_hub.cli.command_exits import not_implemented
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.core.bench.bench_cases import CASE_ID_PATTERN, MAX_CASES
from agent_hub.core.bench.bench_plan import ARMS
from agent_hub.core.bench.bench_session import EFFORTS

COMMAND: Final = "bench"
DEFAULT_RUNS: Final = 3
MAX_RUNS: Final = 100
DEFAULT_PARALLEL: Final = 3
MAX_PARALLEL: Final = 16
DEFAULT_BUDGET_USD: Final = 15.0
MAX_BUDGET_USD: Final = 1000.0
# The script's default: at about $0.035 a turn, $0.90 cut 11 of 15 runs short (2026-09-27).
DEFAULT_PER_RUN_USD: Final = 2.0
DEFAULT_ARMS: Final = ",".join(ARMS)
LABEL_FORMAT: Final = "bench-%Y%m%d-%H%M"
EFFORT_VARIABLE: Final = "BENCH_EFFORT"
DEFAULT_EFFORT: Final = "medium"
NOT_SELECTED: Final = "module bench is not selected"
# The options only a run reads, as their parameter names and their flags.
_RUN_OPTIONS: Final = (
    ("runs", "--runs"),
    ("arms", "--arms"),
    ("cases", "--cases"),
    ("budget", "--budget"),
    ("per_run", "--per-run"),
    ("parallel", "--parallel"),
    ("label", "--label"),
    ("trace", "--trace"),
)
# A case id, and a label: either names a file and a folder.
_CASE_ID: Final = re.compile(CASE_ID_PATTERN)
_SEPARATOR: Final = ","
_PATH_STEPS: Final = frozenset({".", ".."})


@dataclass(frozen=True, kw_only=True, slots=True)
class BenchOptions:
    """The run's options, checked: ``cases`` empty means every case; ``label`` None, the clock's."""

    runs: int
    arms: tuple[str, ...]
    cases: tuple[str, ...]
    budget: float
    per_run: float
    parallel: int
    label: str | None
    trace: bool
    effort: str


def _budget(value: float) -> float:
    if not (math.isfinite(value) and 0 < value <= MAX_BUDGET_USD):
        msg = f"use a number of USD above 0, at most {MAX_BUDGET_USD:g}"
        raise typer.BadParameter(msg)
    return value


def _per_run(value: float) -> float:
    if not (math.isfinite(value) and value > 0):
        msg = "use a number of USD above 0"
        raise typer.BadParameter(msg)
    return value


def _arms(value: str) -> str:
    given = value.split(_SEPARATOR)
    if not set(given) <= set(ARMS) or len(set(given)) != len(given):
        msg = "use with, without or both, comma-separated, each once"
        raise typer.BadParameter(msg)
    return value


def _cases(value: str) -> str:
    ids = value.split(_SEPARATOR) if value else []
    if (
        len(ids) > MAX_CASES
        or not all(_CASE_ID.fullmatch(case_id) for case_id in ids)
        or len(set(ids)) != len(ids)
    ):
        msg = "use case ids (1 to 64 of A-Z a-z 0-9 . _ -), comma-separated, each once"
        raise typer.BadParameter(msg)
    return value


def _label(value: str | None) -> str | None:
    # It names a file, folders and maybe a git ref: never a path step or an option.
    if value is not None and (
        not _CASE_ID.fullmatch(value) or value in _PATH_STEPS or value.startswith("-")
    ):
        msg = "use 1 to 64 of A-Z a-z 0-9 . _ -, not . or .., not starting with -"
        raise typer.BadParameter(msg)
    return value


def bench(  # noqa: PLR0913 - one parameter per option of spec D2
    context: typer.Context,
    *,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Only check the graders: each case fails at its merge's parent, passes at it.",
        ),
    ] = False,
    runs: Annotated[
        int, typer.Option("--runs", min=1, max=MAX_RUNS, help="Runs of each case in each arm.")
    ] = DEFAULT_RUNS,
    arms: Annotated[
        str,
        typer.Option(
            "--arms", callback=_arms, help="Arms to run: the hub-workflow plugin on or off."
        ),
    ] = DEFAULT_ARMS,
    cases: Annotated[
        str,
        typer.Option(
            "--cases",
            callback=_cases,
            help="Case ids to run, comma-separated.",
            show_default="all",
        ),
    ] = "",
    budget: Annotated[
        float,
        typer.Option("--budget", callback=_budget, help="USD cap: a wave starts only if it fits."),
    ] = DEFAULT_BUDGET_USD,
    per_run: Annotated[
        float, typer.Option("--per-run", callback=_per_run, help="USD cap of each session.")
    ] = DEFAULT_PER_RUN_USD,
    parallel: Annotated[
        int,
        typer.Option("--parallel", min=1, max=MAX_PARALLEL, help="Runs at the same time."),
    ] = DEFAULT_PARALLEL,
    label: Annotated[
        str | None,
        typer.Option(
            "--label",
            callback=_label,
            help="Name of the results file and the worktrees.",
            show_default=LABEL_FORMAT,
        ),
    ] = None,
    trace: Annotated[
        bool, typer.Option("--trace", help="Keep each session's stream-json trace.")
    ] = False,
) -> None:
    """Benchmark the hub-workflow plugin on closed issues: each case's hidden tests grade it.

    BENCH_EFFORT sets the sessions' effortLevel: low, medium (default) or high.
    """
    _refuse_run_options(context, validate=validate)
    if per_run > budget:
        # Not even a wave of one could start.
        context.fail(f"--per-run {per_run} is above --budget {budget}")
    effort = _effort_or_fail(context, os.environ)
    root = hub_root_or_exit(os.environ, command=COMMAND)
    config = load_hub_config_or_exit(root / FILE_LABEL)
    if config.modules.bench is None:
        context.fail(NOT_SELECTED)
    options = BenchOptions(
        runs=runs,
        arms=tuple(arms.split(_SEPARATOR)),
        cases=tuple(cases.split(_SEPARATOR)) if cases else (),
        budget=budget,
        per_run=per_run,
        parallel=parallel,
        label=label,
        trace=trace,
        effort=effort,
    )
    _start(options, validate=validate)


def _start(options: BenchOptions, *, validate: bool) -> None:
    # The grader check and the runs come with the next tasks of AGH-17.
    del options, validate
    not_implemented()


def _refuse_run_options(context: typer.Context, *, validate: bool) -> None:
    if not validate:
        return
    given = [
        flag
        for name, flag in _RUN_OPTIONS
        if context.get_parameter_source(name) is not ParameterSource.DEFAULT
    ]
    if given:
        context.fail(f"--validate takes no run option: {', '.join(given)}")


def _effort_or_fail(context: typer.Context, environ: Mapping[str, str]) -> str:
    effort = environ.get(EFFORT_VARIABLE) or DEFAULT_EFFORT
    if effort not in EFFORTS:
        context.fail(f"{EFFORT_VARIABLE} must be low, medium or high")
    return effort
