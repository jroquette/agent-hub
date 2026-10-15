"""``hub step worktree|verdict|commits|pr|report``: ``hub run``'s stages as commands.

The issue-to-pr workflow (ADR 0032) runs them as ``hub step`` nodes. Each prints one JSON object
on stdout, the ``output_format`` its node declares, and exits 0; a failure is one
``hub step <name>: <reason>`` line on stderr and exit 1 (other lines, such as the worktree's
``created`` line and its setup script's, also go to stderr). A usage problem exits 2, as in
``hub run``. ``worktree`` reads ``hub.json`` and the developer's branch prefix as ``hub run``
does, before the session, and prints the repo's facts as ``target`` (the worktree, branch, base,
GitHub repo, gate and conventions); ``commits`` and ``pr`` take that object back as
``--target`` and never read ``hub.json`` again, which the session could have edited. A target
whose path leaves the workspace is refused. ``verdict`` reads the session's reply as ``hub run``
does (``session_outcome``).

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
from dataclasses import dataclass
from pathlib import Path
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
    titled_pr,
    unmatched_warning,
)
from agent_hub.cli.run_children import CHILD_HIDDEN, RunChildren, push_env, untrusted_env, without
from agent_hub.cli.run_command import refuse_usage
from agent_hub.cli.run_steps import HOOKS_OFF, WORKTREE_GIT_TIMEOUT, bounded_child
from agent_hub.cli.ship_steps import ship_child, step_timeouts
from agent_hub.cli.worktree_steps import check_branches, create_worktree, worktree_task
from agent_hub.core.hub_config.conventions import EffectiveConventions
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.run_record import RunOutcome, Stage
from agent_hub.core.runner.run_texts import commit_summary, pr_body
from agent_hub.core.runner.session_prompt import prompt_parts
from agent_hub.core.runner.verdict import (
    OutcomeKind,
    SessionReply,
    last_json_line,
    session_outcome,
)

COMMAND: Final = "step"
NO_COMMIT: Final = "no commit on the branch (the session reported done or gave no verdict)"
NO_PR: Final = "no PR was opened for the commits"
UNCOMMITTED: Final = "uncommitted changes in the worktree"
TARGET_TEXTS: Final = ("branch", "base", "default_branch", "github", "gate")
STOPPED: Final = "the implementing session stopped: "

step_app = typer.Typer(name=COMMAND, no_args_is_help=True, help="Run one stage of hub run.")

Issue = Annotated[str, typer.Option("--issue", metavar="ISSUE", help="The issue, <team>-<n>.")]
Repo = Annotated[str, typer.Option("--repo", metavar="REPO", help="The repo's dir in hub.json.")]
Target = Annotated[
    str, typer.Option("--target", metavar="JSON", help="The target hub step worktree printed.")
]


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
            "target": _target_value(children, path),
        }
    )


@step_app.command("verdict")
def verdict(reply: Annotated[str, typer.Argument(help="The session's final message.")]) -> None:
    """Read the session's reply as hub run does: done, or blocked with its question."""
    outcome = session_outcome(
        SessionReply(is_error=False, subtype=None, result=reply, cost_usd=0.0, turns=None)
    )
    blocked = outcome.kind is OutcomeKind.STOPPED
    found = last_json_line(reply) or {}
    summary = found.get("summary") if blocked else outcome.text
    _print(
        {
            "status": RunOutcome.BLOCKED.value if blocked else OutcomeKind.DONE.value,
            "summary": summary if isinstance(summary, str) else "",
            "question": outcome.question,
        }
    )


@step_app.command("commits")
def commits(*, target: Target) -> None:
    """Print the commits on the branch, and whether a tracked change sits beside them."""
    facts = _target(target)
    child, timeout = ship_child(facts.path), step_timeouts().git
    try:
        log = git_output(
            child, "log", "--format=%s", f"{facts.base}..HEAD", environ=os.environ, timeout=timeout
        )
        subjects = [line for line in log.splitlines() if line]
        summary, dirty = "", False
        if subjects:
            summary = _commit_summary(facts)
            # refuse_uncommitted's check: untracked files never reach the PR.
            status = git_output(
                child,
                *("status", "--porcelain", "--untracked-files=no"),
                environ=os.environ,
                timeout=timeout,
            )
            dirty = bool(status.strip())
    except PrStepError as error:
        _fail("commits", error.reason)
    _print({"count": len(subjects), "subjects": list(subjects), "summary": summary, "dirty": dirty})


@step_app.command("pr")
def pr(
    *,
    issue: Issue,
    target: Target,
    summary: Annotated[
        str, typer.Option("--summary", help="The PR's summary; blank, the commit messages.")
    ] = "",
) -> None:
    """Push the branch and open its PR (or find the one open); print its url."""
    facts = _target(target)
    child, timeouts = ship_child(facts.path), step_timeouts()
    workspace = str(facts.workspace)
    pr_target = PrTarget(github=facts.github, base_branch=facts.default_branch, branch=facts.branch)
    try:
        summary = summary if summary.strip() else _commit_summary(facts)
        push_branch(child, target=pr_target, environ=os.environ, timeouts=timeouts)
        subject = git_output(
            child, "log", "-1", "--format=%s", environ=os.environ, timeout=timeouts.git
        )
        conventions = facts.conventions
        titled = titled_pr(subject, conventions=conventions, issue_id=issue, workspace=workspace)
        if titled.unmatched is not None:
            line = unmatched_warning(
                "hub step pr", line=titled.unmatched, commit_title=conventions.commit_title
            )
            typer.echo(line, err=True)
        body = pr_body(issue_id=issue, summary=summary, gate=facts.gate, workspace=workspace)
        opened = open_or_find_pr(
            child,
            target=pr_target,
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
    status: Annotated[str, typer.Option("--status", help="The verdict's status.")] = "",
    question: Annotated[str, typer.Option("--question", help="What a blocked session asked.")] = "",
    count: Annotated[
        str, typer.Option("--commits", help="The commit count (blank: none were read).")
    ] = "",
    dirty: Annotated[
        str, typer.Option("--dirty", help="true: a tracked change sits beside the commits.")
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
    elif dirty == "true":
        # As hub run's gate: the PR holds the commits only (refuse_uncommitted).
        delivery, stage, reason = RunOutcome.FAILED, Stage.VERIFYING, UNCOMMITTED
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


@dataclass(frozen=True, kw_only=True, slots=True)
class StepTarget:
    """The repo's facts ``worktree`` read from ``hub.json`` before the session."""

    path: Path
    workspace: Path
    branch: str
    base: str
    default_branch: str
    github: str
    gate: str
    conventions: EffectiveConventions


def _target_value(children: RunChildren, path: Path) -> dict[str, JsonValue]:
    conventions = children.conventions
    return {
        "path": str(path),
        "branch": children.branch,
        "base": children.base,
        "default_branch": children.default_branch,
        "github": children.github,
        "gate": children.gate,
        "conventions": {
            "branch": conventions.branch,
            "commit_title": conventions.commit_title,
            "pr_title": conventions.pr_title,
            "titles_configured": conventions.titles_configured,
            "pr_title_explicit": conventions.pr_title_explicit,
        },
    }


def _target(text: str) -> StepTarget:
    """``--target`` checked: the keys ``worktree`` prints, its path an existing folder inside the
    hub's workspace; else exit 2."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    workspace = hub_checkout(
        root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN)
    ).parent
    try:
        value = json.loads(text)
        names = value["conventions"]
        conventions = EffectiveConventions(
            branch=_string(names, "branch"),
            commit_title=_string(names, "commit_title"),
            pr_title=_string(names, "pr_title"),
            titles_configured=names["titles_configured"] is True,
            pr_title_explicit=names["pr_title_explicit"] is True,
        )
        path = Path(_string(value, "path")).resolve()
        facts = StepTarget(
            path=path,
            workspace=workspace,
            conventions=conventions,
            **{key: _string(value, key) for key in TARGET_TEXTS},
        )
    except (ValueError, KeyError, TypeError) as error:
        raise typer.BadParameter(f"not a worktree target: {error}", param_hint="--target") from None
    if not (path.is_relative_to(workspace.resolve()) and path.is_dir()):
        raise typer.BadParameter("the path leaves the workspace", param_hint="--target")
    return facts


def _string(value: object, key: str) -> str:
    found = value[key] if isinstance(value, dict) else None
    if not isinstance(found, str):
        raise TypeError(f"{key} is not a string")
    return found


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


def _commit_summary(facts: StepTarget) -> str:
    messages = git_output(
        ship_child(facts.path),
        *("log", "--format=%B", f"{facts.base}..HEAD"),
        environ=os.environ,
        timeout=step_timeouts().git,
    )
    return commit_summary(messages, workspace=str(facts.workspace))


def _print(value: dict[str, JsonValue]) -> None:
    typer.echo(json.dumps(value, sort_keys=True))


def _fail(name: str, reason: str) -> NoReturn:
    fail(f"hub {COMMAND} {name}: {reason.rstrip()}")
