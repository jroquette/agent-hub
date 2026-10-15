"""``hub step worktree|commits|pr|report``: ``hub run``'s stages as commands a workflow runs.

The issue-to-pr workflow (ADR 0032) runs them as ``hub step`` nodes. Each prints one JSON object
on stdout, the ``output_format`` its node declares, and exits 0; a failure is one
``hub step <name>: <reason>`` line on stderr and exit 1 (other lines, such as the worktree's
``created`` line and its setup script's, also go to stderr). A usage problem exits 2, as in
``hub run``. ``worktree``, ``commits`` and ``pr`` read ``hub.json`` and the developer's branch
prefix as ``hub run`` does and derive the repo's worktree, branch and base from ``--issue`` and
``--repo`` (``RunChildren``): no path comes from another node's output.

Tokens are narrowed per call from the caller's environment, as in ``hub run``: git's reads, the
worktree add and the repo's setup script get ``untrusted_env``; only the fetch, the push and
``gh`` get ``push_env``, each after the push guard checked the clone's config. No step reads or
writes the tracker: ``report`` only computes the delivery (``delivered``, ``no_changes``,
``blocked`` or ``failed``) from what the earlier steps printed; ADR 0030's writes are the
parent's (``hub workflow run``, ``hub run``).
"""

import json
import os
import shutil
from typing import Annotated, Final, NoReturn

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import effective_with_prefix_or_fail
from agent_hub.cli.errors import ChildTimedOutError, PrStepError, WorktreeError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.pr_steps import (
    PrTarget,
    git_output,
    open_or_find_pr,
    push_branch,
    refuse_risky_config,
    refuse_uncommitted,
    titled_pr,
    unmatched_warning,
)
from agent_hub.cli.run_children import CHILD_HIDDEN, RunChildren, push_env, untrusted_env, without
from agent_hub.cli.run_command import refuse_usage
from agent_hub.cli.run_steps import HOOKS_OFF, WORKTREE_GIT_TIMEOUT, bounded_child
from agent_hub.cli.ship_steps import ship_child, step_timeouts
from agent_hub.cli.worktree_steps import check_branches, create_worktree, worktree_task
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.run_record import RunOutcome, Stage
from agent_hub.core.runner.run_texts import commit_summary, pr_body
from agent_hub.core.runner.session_prompt import prompt_parts

COMMAND: Final = "step"
NO_COMMIT: Final = "no commit on the branch (the session reported done or gave no verdict)"
NO_PR: Final = "no PR was opened for the commits"
STOPPED: Final = "the implementing session stopped: "

step_app = typer.Typer(name=COMMAND, no_args_is_help=True, help="Run one stage of hub run.")

Issue = Annotated[str, typer.Option("--issue", metavar="ISSUE", help="The issue, <team>-<n>.")]
Repo = Annotated[str, typer.Option("--repo", metavar="REPO", help="The repo's dir in hub.json.")]


@step_app.command("worktree")
def worktree(context: typer.Context, *, issue: Issue, repo: Repo) -> None:
    """Make (or keep) the issue's worktree in the repo; print its path, branch and prompt texts."""
    children = _children(context, issue=issue, repo=repo)
    name = "worktree"
    git = shutil.which("git", path=os.environ.get("PATH", ""))
    if git is None:
        _fail(name, "git is not on PATH; install git")
    git = os.path.abspath(git)
    if os.path.lexists(children.repo_path / ".git"):
        # The fetch is the first call with the GitHub tokens: the clone's config is checked first.
        _guarded(name, children, use="a fetch would use", outcome="nothing was fetched")
    try:
        task = worktree_task(
            children.config,
            name=children.slug,
            branch_prefix=children.branch_prefix,
            only=repo,
            hub=children.hub,
            git=git,
            env=untrusted_env(os.environ),
            fetch_env=push_env(os.environ),
            fetch_options=HOOKS_OFF,
            add_options=("-c", f"core.hooksPath={os.devnull}"),
            git_timeout=WORKTREE_GIT_TIMEOUT,
            runner=bounded_child,
        )
        check_branches(task)
        path = create_worktree(task, repo, echo=lambda line: typer.echo(line, err=True))
    except (WorktreeError, ChildTimedOutError) as error:
        _fail(name, str(error).replace(git, "git"))
    except OSError as error:
        _fail(name, f"git could not run: {error.strerror or error}")
    entry = next(entry for entry in children.config.repos if entry.dir == repo)
    parts = prompt_parts(
        sensitive=children.config.guard.ask_before_edit,
        fast_gate=entry.check_fast,
        full_gate=entry.check,
        issue_id=issue,
        prefix=f"{children.team}-",
        commit_title=children.conventions.commit_title,
    )
    _print(
        {
            "path": str(path),
            "branch": children.branch,
            "base": children.base,
            "hub": str(children.hub),
            "hub_name": children.hub.name,
            "check": children.gate,
            "prompt": dict(parts),
        }
    )


@step_app.command("commits")
def commits(context: typer.Context, *, issue: Issue, repo: Repo) -> None:
    """Print the commits on the issue's branch; with any, no tracked change may sit beside them."""
    children = _children(context, issue=issue, repo=repo)
    child, timeout = ship_child(children.worktree), step_timeouts().git
    try:
        log = git_output(
            child,
            "log",
            "--format=%s",
            f"{children.base}..HEAD",
            environ=os.environ,
            timeout=timeout,
        )
        subjects = [line for line in log.splitlines() if line]
        summary = ""
        if subjects:
            refuse_uncommitted(child, environ=os.environ, timeout=timeout)
            summary = _commit_summary(children)
    except PrStepError as error:
        _fail("commits", error.reason)
    _print({"count": len(subjects), "subjects": list(subjects), "summary": summary})


@step_app.command("pr")
def pr(
    context: typer.Context,
    *,
    issue: Issue,
    repo: Repo,
    summary: Annotated[
        str, typer.Option("--summary", help="The PR's summary; blank, the commit messages.")
    ] = "",
) -> None:
    """Push the issue's branch and open its PR (or find the one open); print its url."""
    children = _children(context, issue=issue, repo=repo)
    child, timeouts = ship_child(children.worktree), step_timeouts()
    workspace = str(children.workspace)
    target = PrTarget(
        github=children.github, base_branch=children.default_branch, branch=children.branch
    )
    try:
        summary = summary if summary.strip() else _commit_summary(children)
        push_branch(child, target=target, environ=os.environ, timeouts=timeouts)
        subject = git_output(
            child, "log", "-1", "--format=%s", environ=os.environ, timeout=timeouts.git
        )
        conventions = children.conventions
        titled = titled_pr(subject, conventions=conventions, issue_id=issue, workspace=workspace)
        if titled.unmatched is not None:
            line = unmatched_warning(
                "hub step pr", line=titled.unmatched, commit_title=conventions.commit_title
            )
            typer.echo(line, err=True)
        body = pr_body(issue_id=issue, summary=summary, gate=children.gate, workspace=workspace)
        opened = open_or_find_pr(
            child,
            target=target,
            title=titled.title,
            body=body,
            draft=False,
            environ=os.environ,
            timeout=timeouts.gh,
        )
    except PrStepError as error:
        _fail("pr", error.reason)
    _print(
        {
            "url": opened.url,
            "found": opened.found,
            "summary": summary,
            "title_unmatched": titled.unmatched,
        }
    )


@step_app.command("report")
def report(
    *,
    status: Annotated[str, typer.Option("--status", help="The session's verdict status.")] = "",
    question: Annotated[str, typer.Option("--question", help="What a blocked session asked.")] = "",
    count: Annotated[
        str, typer.Option("--commits", help="The commit count (blank: none were read).")
    ] = "",
    url: Annotated[str, typer.Option("--pr", help="The PR's url (blank: none opened).")] = "",
    summary: Annotated[str, typer.Option("--summary", help="The PR's summary.")] = "",
) -> None:
    """Print the run's delivery from the earlier steps' outputs; the tracker is not touched."""
    if count and not (count.isascii() and count.isdecimal()):
        raise typer.BadParameter("use a count of commits, or nothing", param_hint="--commits")
    stage, reason = "", ""
    if status == RunOutcome.BLOCKED:
        delivery, stage, reason = RunOutcome.BLOCKED, Stage.IMPLEMENTING, STOPPED + question
    elif not int(count or "0"):
        delivery, stage, reason = RunOutcome.NO_CHANGES, Stage.IMPLEMENTING, NO_COMMIT
    elif url:
        delivery = RunOutcome.DELIVERED
    else:
        delivery, stage, reason = RunOutcome.FAILED, Stage.PR_OPEN, NO_PR
    delivered = delivery is RunOutcome.DELIVERED
    _print(
        {
            "delivery": delivery.value,
            "stage": str(stage),
            "reason": reason,
            "question": question if delivery is RunOutcome.BLOCKED else "",
            "pr": url if delivered else "",
            "summary": summary if delivered else "",
        }
    )


def _children(context: typer.Context, *, issue: str, repo: str) -> RunChildren:
    root = hub_root_or_exit(os.environ, command=COMMAND)
    hub = hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))
    hub_config = load_hub_config_or_exit(hub / FILE_LABEL)
    refuse_usage(context, hub_config, issue=issue, repo=repo)
    effective, prefix = effective_with_prefix_or_fail(context, hub_config, home=hub)
    return RunChildren(
        config=effective.config, hub=hub, repo=repo, issue_id=issue, branch_prefix=prefix
    )


def _guarded(name: str, children: RunChildren, *, use: str, outcome: str) -> None:
    try:
        refuse_risky_config(
            ship_child(children.repo_path),
            github=children.github,
            environ=os.environ,
            timeout=step_timeouts().git,
            use=use,
            outcome=outcome,
        )
    except PrStepError as error:
        _fail(name, error.reason)


def _commit_summary(children: RunChildren) -> str:
    messages = git_output(
        ship_child(children.worktree),
        *("log", "--format=%B", f"{children.base}..HEAD"),
        environ=os.environ,
        timeout=step_timeouts().git,
    )
    return commit_summary(messages, workspace=str(children.workspace))


def _print(value: dict[str, JsonValue]) -> None:
    typer.echo(json.dumps(value, sort_keys=True))


def _fail(name: str, reason: str) -> NoReturn:
    fail(f"hub {COMMAND} {name}: {reason.rstrip()}")
