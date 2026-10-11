"""``hub ship``: an issue's task worktrees checked, pushed and opened as PRs.

The hub is ``AGENT_HUB_ROOT`` or the cwd; run from a worktree of the hub repo, its main checkout
is the hub, as for ``hub run``. Without ``ISSUE`` the issue is the one of the task worktree the
cwd is in. Usage problems exit 2 before any tracker call or child process: an issue not shaped
``<team>-<n>`` for a team of ``hub.json``, more than one issue, a folder that is not a hub, no
``ISSUE`` outside a task worktree, a malformed ``hub.local.json`` or no branch prefix. Then the
issue is read once, before any child (spec D-read); every later failure exits 1.
"""

import os
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import effective_with_prefix_or_fail
from agent_hub.cli.errors import PrStepError, ShipError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.run_children import (
    CHILD_HIDDEN,
    gate_command,
    pr_create_command,
    pr_edit_command,
    push_command,
    without,
    would_run_line,
)
from agent_hub.cli.ship_set import ShipSet, issue_from_cwd, shipping_set
from agent_hub.cli.ship_steps import (
    PREFIX,
    ShipRun,
    body_file_path,
    pr_title,
    ship_child,
    ship_issue,
    tracker_failure_line,
    tracker_writes,
)
from agent_hub.cli.tracker_client import missing_key_line, resolve_tracker_client, transport_line
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.team_keys import team_of, teams_text
from agent_hub.core.runner.report_writes import REVIEW_STATE, call_line
from agent_hub.core.runner.ship_texts import ship_body
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN, Issue, TrackerClient

COMMAND: Final = "ship"
# A PR url in the dry run's link edits and comment: the PRs are not opened.
DRY_RUN_URL: Final = "<PR url of {repo}>"
NOT_IN_TASK_WORKTREE: Final = (
    "give ISSUE or run hub ship from a task worktree (<repo>/.claude/worktrees/<team>-<n>[-<desc>])"
)


def ship(
    context: typer.Context,
    issue: Annotated[
        str | None,
        typer.Argument(
            metavar="[ISSUE]",
            help="The tracker issue, <team>-<n> (DEM-1); by default the cwd's task worktree's.",
            show_default=False,
        ),
    ] = None,
    *,
    draft: Annotated[bool, typer.Option("--draft", help="Open the PRs as drafts.")] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print what would run; change nothing.")
    ] = False,
) -> None:
    """Ship an issue: each changed repo's check, push and PR, the PRs linked, the issue to review.

    The repos are those whose task worktree for the issue has commits ahead of origin's default
    branch (as last fetched; hub ship does not fetch). Every check passes before any push. Run
    again after a success, hub ship finds the PRs already open and posts one more comment on
    the issue.
    """
    root = hub_root_or_exit(os.environ, command=COMMAND)
    hub = hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))
    hub_config = load_hub_config_or_exit(hub / FILE_LABEL)
    workspace = hub.parent
    issue_id = issue if issue is not None else _cwd_issue(context, hub_config, workspace)
    _refuse_issue(context, hub_config, issue=issue_id)
    effective, prefix = effective_with_prefix_or_fail(context, hub_config, home=hub)
    # hub.json with the developer's local values over it: the transport may be theirs.
    config = effective.config
    missing = missing_key_line(config, os.environ, command=COMMAND)
    if missing is not None:
        fail(missing)
    typer.echo(transport_line(config), err=True)
    client = resolve_tracker_client(config, os.environ, hub_root=hub)
    picked = _read_issue_or_exit(client, issue_id)
    try:
        found = shipping_set(
            config,
            workspace=workspace,
            issue_id=issue_id,
            branch_prefix=prefix,
            environ=os.environ,
        )
    except ShipError as error:
        fail(f"{PREFIX}: {error}")
    _print_set(found)
    # One ShipRun for both paths: the dry run prints the writes the live ship would make.
    ship_run = ShipRun(
        targets=found.targets,
        issue=picked,
        draft=draft,
        hub=hub,
        environ=os.environ,
        client=client,
        review_state=REVIEW_STATE,
        failed_label=config.tracker.failed_label,
    )
    if dry_run:
        _print_dry_run(ship_run)
        return
    raise typer.Exit(ship_issue(ship_run))


def _print_set(found: ShipSet) -> None:
    for target in found.targets:
        typer.echo(f"ship: {target.repo}  {shown_text(target.branch)}")
    for target in found.skipped:
        typer.echo(f"skipped: {target.repo} (no commits ahead of origin/{shown_text(target.base)})")


def _print_dry_run(run: ShipRun) -> None:
    """Every child and tracker write a live ship would make, per target in ``hub.json`` order;
    the PRs' urls are placeholders. Only git reads run (each title's ``git log``): no check,
    push or ``gh``, no tracker write, no log or body file."""
    urls = tuple(DRY_RUN_URL.format(repo=target.repo) for target in run.targets)
    body = ship_body(issue_id=run.issue.id, issue_url=run.issue.url)
    for target, url in zip(run.targets, urls, strict=True):
        cwd = target.worktree
        try:
            title = pr_title(run, target, ship_child(cwd))
        except PrStepError as error:
            fail(f"{PREFIX}: {target.repo}: {error.reason}")
        pr = pr_create_command(
            github=target.github,
            base=target.base,
            branch=target.branch,
            title=title,
            body=body,
            draft=run.draft,
        )
        for argv in (gate_command(target.check), push_command(target.branch), pr):
            typer.echo(would_run_line(argv, cwd=cwd))
        if len(urls) > 1:
            edit = pr_edit_command(url, body_file_path(run, target))
            typer.echo(would_run_line(edit, cwd=cwd))
    for write in tracker_writes(run, urls):
        typer.echo(f"would call: {shown_text(call_line(write))}")


def _cwd_issue(context: typer.Context, config: HubConfig, workspace: Path) -> str:
    try:
        cwd = Path.cwd()
    except OSError:
        context.fail(NOT_IN_TASK_WORKTREE)
    found = issue_from_cwd(
        cwd,
        workspace=workspace,
        repos=[entry.dir for entry in config.repos],
        teams=config.tracker.team_keys,
    )
    if found is None:
        context.fail(NOT_IN_TASK_WORKTREE)
    return found


def _refuse_issue(context: typer.Context, config: HubConfig, *, issue: str) -> None:
    teams = config.tracker.team_keys
    if ISSUE_ID_PATTERN.fullmatch(issue) and team_of(issue, teams):
        return
    team = config.tracker.default_team
    if len(teams) == 1:
        context.fail(f"issue must look like {team}-<n> (e.g. {team}-1)")
    context.fail(
        f"issue must look like <TEAM>-<n> (e.g. {team}-1); use one of: {teams_text(teams)}"
    )


def _read_issue_or_exit(client: TrackerClient, issue_id: str) -> Issue:
    # The one read of the ship (D-read): a failure ends it before any child runs.
    try:
        return client.get_issue(issue_id)
    except TrackerError as error:
        fail(tracker_failure_line(error))
