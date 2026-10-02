"""``hub bench``: the configuration benchmark of the ``bench`` module (spec D2, Q-3).

The hub is ``AGENT_HUB_ROOT`` or the cwd; its ``hub.json`` must select ``bench``. Usage problems
exit 2 before any read of the cases or any child process: an option out of its bound,
``--validate`` with a run option, ``BENCH_EFFORT`` (the sessions' ``effortLevel``; unset or
empty is ``medium``) other than ``low``, ``medium`` or ``high``, a folder that is not a hub, a
hub without ``bench``. An invalid ``hub.json`` exits 1 with the reader's lines.

``--validate`` checks the graders and never runs ``claude``: each case not excluded is graded at
its merge's parent (it must fail) and at its merge (it must pass), one line each; a wrong grade
or a failed step exits 1. A run takes the cases ``--cases`` names (all when empty), runs each in
each arm ``--runs`` times within ``--budget`` and prints the records and the summary; a job whose
step failed exits 1 after the summary. The label's default and each record's ``ts`` read the
local clock (``now``). The steps are ``bench_steps``.
"""

import datetime
import math
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

import typer
from typer._click.core import ParameterSource

from agent_hub.cli.bench_steps import (
    BenchSteps,
    SessionPlan,
    cases_or_exit,
    workspace_lock_or_exit,
)
from agent_hub.cli.command_exits import FAILURE, fail
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit, main_checkout
from agent_hub.cli.run_children import SESSION_HIDDEN, without
from agent_hub.core.bench.bench_cases import CASE_ID_PATTERN, MAX_CASES
from agent_hub.core.bench.bench_plan import ARMS, jobs, run_cases
from agent_hub.core.bench.bench_session import EFFORTS, plugin_id
from agent_hub.core.bench.bench_summary import NO_CASES_TO_RUN, NOTHING_TO_VALIDATE
from agent_hub.core.hub_config.model import HubConfig

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
    if validate:
        _validate(root, config)
    else:
        _run(root, config, options)


def _validate(root: Path, config: HubConfig) -> None:
    """Grade each case at its merge's parent and at its merge; exit 1 on any wrong grade."""
    cases = cases_or_exit(root, repos=[repo.dir for repo in config.repos])
    if not cases:
        typer.echo(NOTHING_TO_VALIDATE)
        return
    steps = BenchSteps(workspace=_hub_checkout(root).parent, environ=os.environ)
    with workspace_lock_or_exit(steps.workspace):
        right = steps.validate(cases)
    if not right:
        raise typer.Exit(FAILURE)


def now() -> datetime.datetime:
    """The run's clock (tests replace it): the local time, as the script's ``time.strftime``."""
    return datetime.datetime.now().astimezone()


def _run(root: Path, config: HubConfig, options: BenchOptions) -> None:
    """Run the cases ``options`` names in each arm within the budget; exit 1 if a job failed."""
    every = cases_or_exit(root, repos=[repo.dir for repo in config.repos])
    cases = run_cases(every, ids=options.cases)
    if not cases:
        typer.echo(NO_CASES_TO_RUN)
        return
    session = SessionPlan(
        label=options.label or now().strftime(LABEL_FORMAT),
        plugin=plugin_id(config.project.name),
        effort=options.effort,
        per_run=options.per_run,
        trace=options.trace,
    )
    steps = BenchSteps(workspace=_hub_checkout(root).parent, environ=os.environ)
    planned = jobs(cases, arms=options.arms, runs=options.runs)
    with workspace_lock_or_exit(steps.workspace):
        right = steps.run(
            planned, session=session, parallel=options.parallel, budget=options.budget, clock=now
        )
    if not right:
        raise typer.Exit(FAILURE)


def _hub_checkout(root: Path) -> Path:
    """The hub's main checkout; git runs only when ``root`` is a worktree (its ``.git`` a file)."""
    if not os.path.isfile(root / ".git"):
        return root
    git = shutil.which("git")
    if git is None:
        fail(f"hub {COMMAND}: git is not on PATH; install git")
    try:
        environ = without(os.environ, SESSION_HIDDEN)
        return main_checkout(root, git=os.path.abspath(git), environ=environ)
    except OSError as error:
        fail(f"hub {COMMAND}: git could not run: {error.strerror or error}")


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
