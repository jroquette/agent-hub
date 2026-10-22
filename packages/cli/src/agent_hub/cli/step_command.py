"""``hub step worktree|verdict|commits|pr|report``: ``hub run``'s stages as commands; and
``hub step ticket-brief|preflight|change-request|decide|amend-plan``, the ticket records an
``implement`` run writes into the hub (``step_records``), ``pending-decision``, the owner's
decision a new run follows, ``outcome``, a merged ticket's outcome (written once), and
``preflight-due``, whether a dependent still has to read a blocker's outcome.

The issue-to-pr workflow (ADR 0032) runs them as ``hub step`` nodes. Each prints one JSON object
on stdout, the ``output_format`` its node declares, and exits 0; a failure is one
``hub step <name>: <reason>`` line on stderr and exit 1 (other lines, such as the worktree's
``created`` line and its setup script's, also go to stderr). A usage problem exits 2, as in
``hub run``. ``worktree`` reads ``hub.json`` and the developer's branch prefix as ``hub run``
does, before the session, and prints the repo's facts as ``target`` (the worktree, branch, base,
GitHub repo, gate and conventions); ``commits`` and ``pr`` take that object back as
``--target`` and never read ``hub.json`` again, which the session could have edited. A target
whose path leaves the workspace is refused. ``verdict`` reads the session's reply as ``hub run``
does (``session_outcome``), from stdin, and the ``discovery`` its last JSON line reports (one
line, ``""`` when none: the ``implement`` workflow loops back to preflight on one).

Tokens are narrowed per call from the caller's environment, as in ``hub run``: git's reads, the
worktree add and the repo's setup script get ``untrusted_env``; only the fetch, the push and
``gh`` get ``push_env``, each after the push guard checked the clone's config. No step reads or
writes the tracker: ``report`` only computes the delivery (``delivered``, ``no_changes``,
``blocked`` or ``failed``) from what the earlier steps printed; ADR 0030's writes are the
parent's (``hub workflow run``, ``hub run``).

The record writers run in the hub's main checkout and never commit; each prints the hub-relative
``path`` it wrote (``change-request`` and ``preflight`` take the run's id from
``AGENT_HUB_RUN_ID``, which the engine gives the run's steps; ``preflight`` builds the run from
the agent's findings), and a refusal (a record the readers could not read, a
second decision, a decision without a person, a plan that moved, a link) is a failure that
writes nothing.

That parent runs its ``hub step`` nodes in process (``run_in_process``): the same code with
``hub run``'s children (in the caller's group), timeouts and lines (the worktree's on stdout, a
warning naming the parent's command), the node's stdin given, its output kept instead of printed
and a failure raised with its reason as written (an exit's, from its last stderr line). An
interrupt (Ctrl-C) is not a failure: it ends the parent as it would end ``hub run``.
"""

import contextlib
import io
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, NoReturn, TextIO

import typer
from typer._click.exceptions import ClickException

from agent_hub.cli import step_records
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
from agent_hub.cli.run_children import (
    CHILD_HIDDEN,
    RUN_ID_VARIABLE,
    RunChildren,
    push_env,
    untrusted_env,
    without,
)
from agent_hub.cli.run_command import refuse_usage
from agent_hub.cli.run_steps import (
    HOOKS_OFF,
    SESSION_OUTPUT_LIMIT,
    WORKTREE_GIT_TIMEOUT,
    bounded_child,
)
from agent_hub.cli.ship_steps import ship_child, step_timeouts
from agent_hub.cli.worktree_steps import check_branches, create_worktree, worktree_task
from agent_hub.core.features.ticket_writes import PreflightFacts, TicketRecordError
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
from agent_hub.core.workflows.failures import NodeFailedError, kind_for_exit

COMMAND: Final = "step"
NO_COMMIT: Final = "no commit on the branch (the session reported done or gave no verdict)"
NO_PR: Final = "no PR was opened for the commits"
# The largest reply read, the session's output cap (``run_steps.SESSION_OUTPUT_LIMIT``); a
# longer one fails the step.
MAX_REPLY_BYTES: Final = SESSION_OUTPUT_LIMIT
UNCOMMITTED: Final = "uncommitted changes in the worktree"
TARGET_TEXTS: Final = ("branch", "base", "default_branch", "github", "gate")
STOPPED: Final = "the implementing session stopped: "
# A discovery (a broken plan assumption, implement's loop back to preflight) is one line.
MAX_DISCOVERY_CHARS: Final = 1000
FENCE_RUN: Final = re.compile("`{3,}")
COMMIT: Final = re.compile("[0-9a-f]{7,40}")

step_app = typer.Typer(name=COMMAND, no_args_is_help=True, help="Run one stage of hub run.")

Issue = Annotated[str, typer.Option("--issue", metavar="ISSUE", help="The issue, <team>-<n>.")]
Repo = Annotated[str, typer.Option("--repo", metavar="REPO", help="The repo's dir in hub.json.")]
Target = Annotated[
    str, typer.Option("--target", metavar="JSON", help="The target hub step worktree printed.")
]
Feature = Annotated[
    str, typer.Option("--feature", metavar="SLUG", help="The folder under brain/features/.")
]
Ticket = Annotated[str, typer.Option("--ticket", metavar="TICKET", help="The ticket's key or id.")]
Request = Annotated[
    int, typer.Option("--request", metavar="N", min=1, help="The change request's number.")
]


class StepFailedError(Exception):
    """An in-process step failed: its reason, as ``hub run`` records it."""


@dataclass
class InProcess:
    """A step run by the issue-to-pr parent: where its lines and warnings go, whom a warning
    names, its stdin, and the output it made."""

    echo: Callable[[str], None]
    prefix: str
    stdin: bytes
    stderr: TextIO
    output: dict[str, JsonValue] | None = None


_IN_PROCESS: ContextVar[InProcess | None] = ContextVar("in_process", default=None)


def run_in_process(
    arguments: Sequence[str], *, stdin: bytes, echo: Callable[[str], None], prefix: str
) -> str:
    """``hub step <arguments>`` run here; its JSON output. A step's failure is ``exec_failed``
    with its reason, an exit the kind of its code with its last stderr line, a usage problem
    ``config``; ``KeyboardInterrupt`` propagates."""
    errors = io.StringIO()
    mode = InProcess(echo, prefix, stdin, sys.stderr)
    token = _IN_PROCESS.set(mode)
    try:
        command = typer.main.get_command(step_app)
        with (
            contextlib.redirect_stderr(errors),
            command.make_context("hub step", [*arguments]) as context,
        ):
            command.invoke(context)
    except StepFailedError as error:
        raise NodeFailedError("exec_failed", str(error)) from None
    except ClickException as error:
        raise NodeFailedError("config", error.format_message()) from None
    except typer.Exit as exited:
        lines = errors.getvalue().splitlines() or [f"hub step exited {exited.exit_code}"]
        raise NodeFailedError(kind_for_exit(exited.exit_code) or "config", lines[-1]) from None
    finally:
        _IN_PROCESS.reset(token)
    if mode.output is None:
        raise NodeFailedError("config", "hub step ended without an output")
    return json.dumps(mode.output, sort_keys=True)


@step_app.command("worktree")
def worktree(
    context: typer.Context,
    *,
    issue: Issue,
    repo: Repo,
    commit: Annotated[
        str,
        typer.Option("--commit", help="Start a new branch here (the commit a preflight checked)."),
    ] = "",
) -> None:
    """Make (or keep) the issue's worktree in the repo; print its path, branch and prompt texts."""
    if commit and not COMMIT.fullmatch(commit):
        raise typer.BadParameter("use a commit id (7 to 40 hex digits)", param_hint="--commit")
    children = _children(context, issue=issue, repo=repo)
    name = "worktree"
    git = shutil.which("git", path=os.environ.get("PATH", ""))
    if git is None:
        _fail(name, "git is not on PATH; install git")
    git = os.path.abspath(git)
    if commit:
        # The base is the local commit the preflight checked: no fetch, so no token is used.
        _local_commit(children, commit)
    elif os.path.lexists(children.repo_path / ".git"):
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
        if commit:
            # The branch starts at the commit the preflight checked, already in the clone.
            task = replace(task, bases={**task.bases, repo: commit}, fetch=False)
        check_branches(task)
        path = create_worktree(task, repo, echo=_note)
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
            "base": commit or children.base,
            "hub": str(children.hub),
            "hub_name": children.hub.name,
            "check": children.gate,
            "prompt": dict(parts),
            "target": _target_value(children, path, base=commit or children.base),
        }
    )


@step_app.command("verdict")
def verdict() -> None:
    """Read the session's reply on stdin as hub run does: done, or blocked with its question."""
    # On stdin, not as an argument: a reply may be longer than one argument holds, or hold NUL.
    mode = _IN_PROCESS.get()
    data = sys.stdin.buffer.read(MAX_REPLY_BYTES + 1) if mode is None else mode.stdin
    if len(data) > MAX_REPLY_BYTES:
        _fail("verdict", "the reply is larger than 1 MiB")
    reply = data.decode(errors="replace")
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
            "discovery": _one_line(found.get("discovery")),
        }
    )


def _one_line(value: object) -> str:
    """A text of the reply on one line of at most ``MAX_DISCOVERY_CHARS``, else ``""``."""
    if not isinstance(value, str):
        return ""
    kept = "".join(c for c in value if c.isprintable() or c.isspace())
    # No run of three backticks: the preflight renders it inside a fence of three.
    return " ".join(FENCE_RUN.sub("`", kept).split())[:MAX_DISCOVERY_CHARS]


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
            mode = _IN_PROCESS.get()
            line = unmatched_warning(
                "hub step pr" if mode is None else mode.prefix,
                line=titled.unmatched,
                commit_title=conventions.commit_title,
            )
            # In process, past the stderr the step's exit reads: the user sees it, as in hub run.
            typer.echo(line, file=sys.stderr if mode is None else mode.stderr)
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


@step_app.command("ticket-brief")
def ticket_brief(*, feature: Feature, ticket: Ticket) -> None:
    """Append the ticket's context brief to tickets/<ticket>/brief.md (a new version)."""
    hub = _hub()
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    _record(
        "ticket-brief",
        lambda: step_records.ticket_brief(
            hub, config, feature=feature, ticket=ticket, now=datetime.now(UTC)
        ),
    )


@step_app.command("preflight")
def preflight(
    *,
    feature: Feature,
    ticket: Ticket,
    findings: Annotated[
        str,
        typer.Option("--findings", metavar="JSON", help="The agent's drift, notes and blockers."),
    ],
    kind: Annotated[
        str, typer.Option("--input", help="none, discovery, declined_change; a gate's decision.")
    ],
    text: Annotated[str, typer.Option("--input-text", help="The discovery, or the note.")] = "",
    commit: Annotated[
        str, typer.Option("--commit", help="Main's commit the preflight read (ticket-brief's).")
    ],
    request: Annotated[
        str, typer.Option("--request", help="The change request it opened or re-checked.")
    ] = "",
    declined: Annotated[
        str,
        typer.Option(
            "--declined-request", help="The declined request a declined change re-checks."
        ),
    ] = "",
    read: Annotated[
        str,
        typer.Option(
            "--read", metavar="TICKET", help="A blocker it read, whatever the agent lists."
        ),
    ] = "",
) -> None:
    """Append one run to tickets/<ticket>/preflight.json, from the preflight's findings."""
    for value, hint in ((request, "--request"), (declined, "--declined-request")):
        if value and not (value.isascii() and value.isdecimal()):
            raise typer.BadParameter("use a request number, or nothing", param_hint=hint)
    hub = _hub()
    facts = PreflightFacts(
        ran_at=datetime.now(UTC),
        plan_version=1,
        commit=commit,
        run_id=os.environ.get(RUN_ID_VARIABLE, ""),
        input=kind,
        input_text=text,
        request=int(request) if request else None,
        declined_request=int(declined) if declined else None,
    )
    _record(
        "preflight",
        lambda: step_records.preflight(
            hub, feature=feature, ticket=ticket, findings=findings.encode(), facts=facts, read=read
        ),
    )


@step_app.command("change-request")
def change_request(
    *,
    feature: Feature,
    ticket: Ticket,
    evidence: Annotated[str, typer.Option("--evidence", help="What the plan got wrong.")],
    proposal: Annotated[str, typer.Option("--proposal", help="The plan change asked.")],
    affected: Annotated[
        str,
        typer.Option("--affected", metavar="TICKETS", help="Affected tickets, comma-separated."),
    ] = "",
    findings: Annotated[
        str, typer.Option("--findings", metavar="JSON", help="The preflight's, checked first.")
    ] = "",
    commit: Annotated[str, typer.Option("--commit", help="Main's commit it read.")] = "",
) -> None:
    """Open change-requests/<n>.md against the plan's current version."""
    hub = _hub()
    names = [name.strip() for name in affected.split(",")]
    run_id = os.environ.get(RUN_ID_VARIABLE, "")
    facts = None
    if findings:
        facts = PreflightFacts(
            ran_at=datetime.now(UTC),
            plan_version=1,
            commit=commit,
            run_id=run_id,
            input="none",
            input_text="",
            request=None,
        )
    _record(
        "change-request",
        lambda: step_records.change_request(
            hub,
            feature=feature,
            ticket=ticket,
            affected=[name for name in names if name],
            run_id=run_id,
            evidence=evidence,
            proposal=proposal,
            now=datetime.now(UTC),
            findings=findings.encode(),
            facts=facts,
        ),
    )


@step_app.command("pending-decision")
def pending_decision(*, feature: Feature, ticket: Ticket) -> None:
    """Print the owner's decision on the ticket's last change request that no run followed."""
    hub = _hub()
    _record("pending-decision", lambda: step_records.pending(hub, feature=feature, ticket=ticket))


@step_app.command("decide")
def decide(
    *,
    feature: Feature,
    request: Request,
    decision: Annotated[str, typer.Option("--decision", help="approved or declined.")],
    decided_by: Annotated[str, typer.Option("--by", help="The person the gate recorded.")],
    note: Annotated[str, typer.Option("--note", help="The note; a decline needs one.")] = "",
) -> None:
    """Record the owner's decision as change-requests/<n>.decision.md, once."""
    hub = _hub()
    _record(
        "decide",
        lambda: step_records.decide(
            hub,
            feature=feature,
            request=request,
            decision=decision,
            decided_by=decided_by,
            note=note,
            now=datetime.now(UTC),
        ),
    )


@step_app.command("amend-plan")
def amend_plan(
    *,
    feature: Feature,
    request: Request,
    summary: Annotated[str, typer.Option("--summary", help="The amendment, one line.")],
) -> None:
    """Append the approved request's A<k> entry to plan.md's Amendments."""
    hub = _hub()
    _record(
        "amend-plan",
        lambda: step_records.amend_plan(hub, feature=feature, request=request, summary=summary),
    )


@step_app.command("outcome")
def outcome(
    *,
    feature: Feature,
    ticket: Ticket,
    pr: Annotated[str, typer.Option("--pr", help="The merged pull request (URL or repo#n).")],
    merged_at: Annotated[
        str, typer.Option("--merged-at", help="When it merged, ISO 8601 with an offset (now).")
    ] = "",
    built: Annotated[str, typer.Option("--built", help="What was built.")],
    changes: Annotated[str, typer.Option("--changes", help="What changed against the plan.")],
    interfaces: Annotated[str, typer.Option("--interfaces", help="The final interfaces.")],
) -> None:
    """Record the merged ticket's tickets/<ticket>/outcome.md once; a second run writes nothing."""
    hub = _hub()
    _record(
        "outcome",
        lambda: step_records.outcome(
            hub,
            feature=feature,
            ticket=ticket,
            pr=pr,
            merged_at=merged_at or datetime.now(UTC).isoformat(),
            built=built,
            changes=changes,
            interfaces=interfaces,
        ),
    )


@step_app.command("preflight-due")
def preflight_due(
    *,
    feature: Feature,
    ticket: Ticket,
    blocker: Annotated[
        str, typer.Option("--blocker", metavar="TICKET", help="The merged blocker's key or id.")
    ],
) -> None:
    """Print whether the dependent ticket still has to read the merged blocker's outcome."""
    hub = _hub()
    _record(
        "preflight-due",
        lambda: step_records.preflight_due(hub, feature=feature, ticket=ticket, blocker=blocker),
    )


def _hub() -> Path:
    root = hub_root_or_exit(os.environ, command=COMMAND)
    return hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))


def _record(name: str, write: Callable[[], dict[str, JsonValue]]) -> None:
    try:
        written = write()
    except TicketRecordError as error:
        _fail(name, str(error))
    except OSError as error:
        _fail(name, error.strerror or type(error).__name__)
    _print(written)


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


def _target_value(children: RunChildren, path: Path, *, base: str) -> dict[str, JsonValue]:
    conventions = children.conventions
    return {
        "path": str(path),
        "branch": children.branch,
        "base": base,
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


def _local_commit(children: RunChildren, commit: str) -> None:
    """Refuse a ``--commit`` the repo's clone lacks (ticket-brief read it there)."""
    try:
        git_output(
            ship_child(children.repo_path),
            *("rev-parse", "--verify", "-q", f"{commit}^{{commit}}"),
            environ=os.environ,
            timeout=step_timeouts().git,
        )
    except PrStepError:
        why = f"{commit} is not in {children.repo}'s clone; run hub step ticket-brief again"
        _fail("worktree", why)


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


def _note(line: str) -> None:
    if (mode := _IN_PROCESS.get()) is not None:
        mode.echo(line)
        return
    typer.echo(line, err=True)


def _print(value: dict[str, JsonValue]) -> None:
    if (mode := _IN_PROCESS.get()) is not None:
        mode.output = value
        return
    typer.echo(json.dumps(value, sort_keys=True))


def _fail(name: str, reason: str) -> NoReturn:
    if _IN_PROCESS.get() is not None:
        raise StepFailedError(reason)
    fail(f"hub {COMMAND} {name}: {reason.rstrip()}")
