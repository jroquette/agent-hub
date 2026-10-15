"""``hub run``: one tracker issue to a PR, every tracker read and write through the port.

The hub is ``AGENT_HUB_ROOT`` or the cwd; run from a worktree of the hub repo, its main checkout
is the hub (its ``hub.json``, Q-23). Usage problems exit 2 before any tracker call or child
process: an option out of range, an issue not shaped ``<team>-<n>`` for a team of ``hub.json``, a
``--repo`` that is not a repo ``dir`` of ``hub.json``, a folder that is not a hub (D15), a malformed
``hub.local.json`` in the main checkout, or no branch prefix for the developer. The local file's
``tracker.transport`` replaces ``hub.json``'s. An issue whose description lacks a section of the
input brief (ADR 0026) is refused with exit 1 right after the read, before anything is created.
A live run exits 0 when it opened its PR or ended with no changes, 3 when its session stopped for a
human, and 1 on a failure or a tracker report that failed (ADR 0030).
"""

import contextlib
import math
import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

import typer
from typer._click.core import ParameterSource

from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import effective_with_prefix_or_fail
from agent_hub.cli.errors import RunLogError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.run_children import (
    CHILD_HIDDEN,
    RunChildren,
    RunOptions,
    without,
    would_run_line,
)
from agent_hub.cli.run_log import RunLog, new_run_id
from agent_hub.cli.run_report import tracker_cost
from agent_hub.cli.run_steps import LiveRun
from agent_hub.cli.tracker_client import missing_key_line, resolve_tracker_client, transport_line
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.model_tiers import (
    DEFAULT_TIER_MODELS,
    MODEL_NAME_PATTERN,
    RUN_TIER,
)
from agent_hub.core.hub_config.team_keys import team_of, teams_text
from agent_hub.core.runner.brief import check_brief, missing_brief_reason
from agent_hub.core.runner.report_writes import call_line, success_writes
from agent_hub.core.runner.run_record import Stage, picked_data
from agent_hub.core.runner.run_texts import pr_body, success_comment
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN, Issue, TrackerClient

COMMAND: Final = "run"
DEFAULT_MAX_TURNS: Final = 40
DEFAULT_BUDGET_USD: Final = 3.0
# The implementing session's model when hub.json sets no ``models.tiers.medium`` (AGH-180).
DEFAULT_MODEL: Final = DEFAULT_TIER_MODELS[RUN_TIER]
_PREFIX: Final = f"hub {COMMAND}"
# What a dry run shows for what only a live run knows.
DRY_RUN_TEXT: Final = "(dry run)"
DRY_RUN_TITLE: Final = "(dry run: subject of the last commit)"
# Claude Code sets CLAUDECODE in the sessions it runs; a live run there nests claude -p.
NESTED_VARIABLE: Final = "CLAUDECODE"
NESTED_NOTE: Final = "note: launching a nested headless claude from inside a Claude session"


class RunStart(StrEnum):
    """Where a run starts: the implementing session, or the gate on the commits already made."""

    IMPLEMENT = "implement"
    VERIFY = "verify"


class Effort(StrEnum):
    """The implementing session's ``effortLevel``."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _budget(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        msg = "use a number of USD above 0"
        raise typer.BadParameter(msg)
    return value


def _model(value: str) -> str:
    if not MODEL_NAME_PATTERN.fullmatch(value):
        msg = "use 1 to 64 of A-Z a-z 0-9 . _ -"
        raise typer.BadParameter(msg)
    return value


def run(
    context: typer.Context,
    issue: Annotated[
        str, typer.Argument(metavar="ISSUE", help="The tracker issue, <team>-<n> (DEM-1).")
    ],
    *,
    repo: Annotated[
        str,
        typer.Option("--repo", metavar="REPO", help="The repo to change (its dir in hub.json)."),
    ],
    live: Annotated[
        bool, typer.Option("--live", help="Run it; without it, print what would run.")
    ] = False,
    max_turns: Annotated[
        int, typer.Option("--max-turns", min=1, help="Turns of the implementing session.")
    ] = DEFAULT_MAX_TURNS,
    budget: Annotated[
        float,
        typer.Option("--budget", callback=_budget, help="USD cap of the implementing session."),
    ] = DEFAULT_BUDGET_USD,
    model: Annotated[
        str,
        typer.Option(
            "--model",
            callback=_model,
            help="Model of the implementing session; unset, hub.json's models.tiers.medium.",
        ),
    ] = DEFAULT_MODEL,
    start: Annotated[
        RunStart,
        typer.Option("--from", help="verify: gate, PR and report on the commits already made."),
    ] = RunStart.IMPLEMENT,
    effort: Annotated[
        Effort, typer.Option("--effort", help="effortLevel of the implementing session.")
    ] = Effort.MEDIUM,
) -> None:
    """Take one tracker issue to a PR: worktree, implementing session, gate, PR, report."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    hub = hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))
    hub_config = load_hub_config_or_exit(hub / FILE_LABEL)
    refuse_usage(context, hub_config, issue=issue, repo=repo)
    children, client = run_setup(context, hub_config, hub=hub, issue=issue, repo=repo)
    if context.get_parameter_source("model") is ParameterSource.DEFAULT:
        # Not given: the tier's model, the default itself while hub.json sets none (AGH-180).
        model = hub_config.models.model_for(RUN_TIER)
    options = RunOptions(
        live=live, max_turns=max_turns, budget=budget, model=model, start=start, effort=effort
    )
    if not options.live:
        picked = _read_issue_or_exit(client, issue, log=None)
        _refuse_incomplete_brief(picked, issue, log=None)
        _print_dry_run(children, picked, options=options, run_id=new_run_id())
        return
    live_run = begin_live_run(children, client, options=options, run_id=new_run_id())
    raise typer.Exit(live_run.run())


def run_setup(
    context: typer.Context,
    hub_config: HubConfig,
    *,
    hub: Path,
    issue: str,
    repo: str,
    command: str = COMMAND,
) -> tuple[RunChildren, TrackerClient]:
    """The run's children and tracker client: ``hub.json`` with the developer's local values
    over it (the transport may be theirs) and their branch prefix; exit 1 without the key."""
    effective, prefix = effective_with_prefix_or_fail(context, hub_config, home=hub)
    config = effective.config
    missing = missing_key_line(config, os.environ, command=command)
    if missing is not None:
        fail(missing)
    typer.echo(transport_line(config), err=True)
    client = resolve_tracker_client(config, os.environ, hub_root=hub)
    children = RunChildren(config=config, hub=hub, repo=repo, issue_id=issue, branch_prefix=prefix)
    return children, client


def begin_live_run(
    children: RunChildren,
    client: TrackerClient,
    *,
    options: RunOptions,
    run_id: str,
    prefix: str = _PREFIX,
) -> LiveRun:
    """A live run past its ``picked`` record: the issue read once and its brief checked (exit 1
    otherwise, each recorded as ``failed``)."""
    if os.environ.get(NESTED_VARIABLE):
        typer.echo(NESTED_NOTE, err=True)
    issue, hub, config = children.issue_id, children.hub, children.config
    # A live run records from the read on, so a failed read leaves its "failed" record.
    log = RunLog(hub=hub, run_id=run_id, issue_id=issue, repo=children.repo)
    picked = _read_issue_or_exit(client, issue, log=log)
    _refuse_incomplete_brief(picked, issue, log=log)
    try:
        data = picked_data(
            budget=options.budget,
            max_turns=options.max_turns,
            model=options.model,
            transport=config.tracker.transport,
        )
        log.record("picked", data)
    except RunLogError as error:
        fail(f"{prefix}: {error}")
    return LiveRun(
        children=children,
        options=options,
        issue=picked,
        client=client,
        log=log,
        environ=os.environ,
        cost_usd=tracker_cost(client),
    )


def _read_issue_or_exit(client: TrackerClient, issue_id: str, *, log: RunLog | None) -> Issue:
    # The one read of the run (D6, D8): a failure ends it before anything is created.
    try:
        return client.get_issue(issue_id)
    except TrackerError as error:
        if log is not None:
            with contextlib.suppress(RunLogError):
                log.record("failed", {"stage": Stage.PICKED.value, "reason": str(error)})
        fail(str(error))


def _refuse_incomplete_brief(issue: Issue, issue_id: str, *, log: RunLog | None) -> None:
    # The input brief (ADR 0026): a section missing ends the run before anything is created.
    missing = check_brief(issue.description)
    if not missing:
        return
    reason = missing_brief_reason(issue_id, missing)
    if log is not None:
        with contextlib.suppress(RunLogError):
            log.record("failed", {"stage": Stage.PICKED.value, "reason": reason})
    fail(f"{_PREFIX}: {reason}")


def _print_dry_run(
    children: RunChildren, issue: Issue, *, options: RunOptions, run_id: str
) -> None:
    """Every child and tracker write a live run would make, in order; nothing is changed."""
    worktree = children.worktree
    typer.echo(children.worktree_line())
    if options.start == RunStart.IMPLEMENT:
        typer.echo(would_run_line(children.session_argv(issue, options), cwd=worktree))
    typer.echo(would_run_line(children.gate_argv(), cwd=worktree))
    typer.echo(would_run_line(children.push_argv(), cwd=worktree))
    body = pr_body(
        issue_id=issue.id,
        summary=DRY_RUN_TEXT,
        gate=children.gate,
        workspace=str(children.workspace),
    )
    typer.echo(would_run_line(children.pr_argv(title=DRY_RUN_TITLE, body=body), cwd=worktree))
    comment = success_comment(
        run_id=run_id,
        pr_url=DRY_RUN_TEXT,
        summary=DRY_RUN_TEXT,
        workspace=str(children.workspace),
    )
    tracker = children.config.tracker
    for write in success_writes(
        issue,
        review_state=tracker.states.review,
        failed_label=tracker.failed_label,
        blocked_label=tracker.effective_blocked_label,
        comment=comment,
    ):
        typer.echo(f"would call: {shown_text(call_line(write))}")


def refuse_usage(context: typer.Context, config: HubConfig, *, issue: str, repo: str) -> None:
    """Exit 2 unless ``issue`` is shaped ``<team>-<n>`` for a team of ``config`` and ``repo`` is
    one of its repo dirs (``hub run`` and ``hub step``)."""
    teams = config.tracker.team_keys
    if not (ISSUE_ID_PATTERN.fullmatch(issue) and team_of(issue, teams)):
        team = config.tracker.default_team
        if len(teams) == 1:
            context.fail(f"issue must look like {team}-<n> (e.g. {team}-1)")
        context.fail(
            f"issue must look like <TEAM>-<n> (e.g. {team}-1); use one of: {teams_text(teams)}"
        )
    dirs = [entry.dir for entry in config.repos]
    if repo not in dirs:
        context.fail(f"unknown repo in --repo: {shown_path(repo)}; use one of: {' '.join(dirs)}")
