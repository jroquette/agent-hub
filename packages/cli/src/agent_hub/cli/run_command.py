"""``hub run``: one tracker issue to a PR, every tracker read and write through the port.

The hub is ``AGENT_HUB_ROOT`` or the cwd; run from a worktree of the hub repo, its main checkout
is the hub (its ``hub.json``, Q-23). Usage problems exit 2 before any tracker call or child
process: an option out of range, an issue not shaped ``<team>-<n>``, a ``--repo`` that is not a
repo ``dir`` of ``hub.json``, a folder that is not a hub (D15).
"""

import contextlib
import math
import os
import re
import shutil
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.errors import RunLogError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit, main_checkout
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.run_children import (
    CHILD_HIDDEN,
    RunChildren,
    RunOptions,
    without,
    would_run_line,
)
from agent_hub.cli.run_log import RunLog, new_run_id
from agent_hub.cli.run_steps import LiveRun
from agent_hub.cli.tracker_client import missing_key_line, resolve_tracker_client, transport_line
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.runner.report_writes import REVIEW_STATE, call_line, success_writes
from agent_hub.core.runner.run_record import Stage, picked_data
from agent_hub.core.runner.run_texts import pr_body, success_comment
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN, Issue, TrackerClient

COMMAND: Final = "run"
DEFAULT_MAX_TURNS: Final = 40
DEFAULT_BUDGET_USD: Final = 3.0
DEFAULT_MODEL: Final = "sonnet"
MODEL_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,64}")
_PREFIX: Final = f"hub {COMMAND}"
# What a dry run shows for what only a live run knows.
DRY_RUN_TEXT: Final = "(dry run)"
DRY_RUN_TITLE: Final = "(dry run: subject of the last commit)"


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
    if not MODEL_PATTERN.fullmatch(value):
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
        str, typer.Option("--model", callback=_model, help="Model of the implementing session.")
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
    hub = _hub_checkout(root)
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    _refuse_usage(context, config, issue=issue, repo=repo)
    missing = missing_key_line(config, os.environ, command=COMMAND)
    if missing is not None:
        fail(missing)
    typer.echo(transport_line(config), err=True)
    options = RunOptions(
        live=live, max_turns=max_turns, budget=budget, model=model, start=start, effort=effort
    )
    client = resolve_tracker_client(config, os.environ, hub_root=hub)
    children = RunChildren(config=config, hub=hub, repo=repo, issue_id=issue)
    if not options.live:
        picked = _read_issue_or_exit(client, issue, log=None)
        _print_dry_run(children, picked, options=options, run_id=new_run_id())
        return
    # A live run records from the read on, so a failed read leaves its "failed" record.
    log = RunLog(hub=hub, run_id=new_run_id(), issue_id=issue, repo=repo)
    picked = _read_issue_or_exit(client, issue, log=log)
    try:
        data = picked_data(
            budget=options.budget,
            max_turns=options.max_turns,
            model=options.model,
            transport=config.tracker.transport,
        )
        log.record("picked", data)
    except RunLogError as error:
        fail(f"{_PREFIX}: {error}")
    live_run = LiveRun(
        children=children,
        options=options,
        issue=picked,
        client=client,
        log=log,
        environ=os.environ,
    )
    raise typer.Exit(live_run.run())


def _read_issue_or_exit(client: TrackerClient, issue_id: str, *, log: RunLog | None) -> Issue:
    # The one read of the run (D6, D8): a failure ends it before anything is created.
    try:
        return client.get_issue(issue_id)
    except TrackerError as error:
        if log is not None:
            with contextlib.suppress(RunLogError):
                log.record("failed", {"stage": Stage.PICKED.value, "reason": str(error)})
        fail(str(error))


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
    failed_label = children.config.tracker.failed_label
    for write in success_writes(
        issue, review_state=REVIEW_STATE, failed_label=failed_label, comment=comment
    ):
        typer.echo(f"would call: {shown_text(call_line(write))}")


def _hub_checkout(root: Path) -> Path:
    """The hub's main checkout; git runs only when ``root`` is a worktree (its ``.git`` a file)."""
    if not os.path.isfile(root / ".git"):
        return root
    git = shutil.which("git")
    if git is None:
        fail(f"{_PREFIX}: git is not on PATH; install git")
    try:
        environ = without(os.environ, CHILD_HIDDEN)
        return main_checkout(root, git=os.path.abspath(git), environ=environ)
    except OSError as error:
        fail(f"{_PREFIX}: git could not run: {error.strerror or error}")


def _refuse_usage(context: typer.Context, config: HubConfig, *, issue: str, repo: str) -> None:
    team = config.tracker.team
    if not (ISSUE_ID_PATTERN.fullmatch(issue) and issue.startswith(f"{team}-")):
        context.fail(f"issue must look like {team}-<n> (e.g. {team}-1)")
    dirs = [entry.dir for entry in config.repos]
    if repo not in dirs:
        context.fail(f"unknown repo in --repo: {shown_path(repo)}; use one of: {' '.join(dirs)}")
