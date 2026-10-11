"""The live phases of ``hub ship``, in order, each stopping the ship at its first failure.

1. Every target's worktree holds no uncommitted tracked change, then every target's ``check``
   runs, in ``hub.json`` order, before any push (spec D-order). After the checks, each
   worktree is clean again and its HEAD and task branch are where the check found them, so
   what is pushed is what was checked.
2. Per target: the push (after the push guard), then the PR opened or found. A failure lists
   the PRs already open; no PR is linked and the tracker is not written.

Each child runs through ``ship_child``: in the caller's process group, with ``pr_steps``'
environments, timeouts read from ``run_steps``' constants at call time (PD-2). A failure names
the repo and the step, and what is already open; every stderr line starts with ``hub ship:``.
"""

import contextlib
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli import run_steps
from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.command_exits import fail
from agent_hub.cli.errors import ChildTimedOutError, PrStepError
from agent_hub.cli.init_report import shown_path
from agent_hub.cli.pr_steps import (
    ChildCall,
    PrTarget,
    StepTimeouts,
    git_output,
    open_or_find_pr,
    push_branch,
    refuse_uncommitted,
    run_gate,
    titled_pr,
    unmatched_warning,
)
from agent_hub.cli.ship_set import ShipTarget
from agent_hub.core.runner.ship_texts import ship_body
from agent_hub.core.tracker.tracker_client import Issue

PREFIX: Final = "hub ship"
NOTHING_CHECKED: Final = f"{PREFIX}: nothing was checked or pushed"
NOTHING_PUSHED: Final = f"{PREFIX}: nothing was pushed"
NOT_LINKED: Final = f"{PREFIX}: no PR was linked and the issue was not moved"
# The check logs: <hub>/.agent-runs/ship/<ISSUE>-<repo>.log, owner-only (spec Q-2, PD-8).
LOG_FOLDERS: Final = (".agent-runs", "ship")
_LOG_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
_PRIVATE_FILE: Final = 0o600
_PRIVATE_FOLDER: Final = 0o700
PUSH_STEP: Final = "push"
PR_STEP: Final = "pull request"


class _StepError(Exception):
    """A phase 2 step failed for a target: the step and why."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(reason)
        self.step = step
        # One line: a child's message may span several. The step is named once, so a step's
        # own "push failed: " is dropped.
        shown = " ".join(reason.split())
        self.reason = shown.removeprefix(f"{step} failed: ")


@dataclass(frozen=True, kw_only=True, slots=True)
class ShipRun:
    """What a live ship works on: the targets, the issue read, the options and the hub."""

    targets: tuple[ShipTarget, ...]
    issue: Issue
    draft: bool
    hub: Path
    environ: Mapping[str, str]


def ship_issue(run: ShipRun) -> int:
    """Run the phases; 0 when every one passed. A failure prints its lines and exits 1."""
    _refuse_uncommitted(run, after=NOTHING_CHECKED)
    checked = tuple(_check(run, target) for target in run.targets)
    # What was checked is what is pushed: no change left beside the commits, no commit added.
    _refuse_uncommitted(run, after=NOTHING_PUSHED)
    for target, heads in zip(run.targets, checked, strict=True):
        if _heads(run, target) != heads:
            fail(f"{PREFIX}: {target.repo}: the branch moved during the check; nothing was pushed")
    _open_prs(run)
    return 0


def step_timeouts() -> StepTimeouts:
    """The shared steps' timeouts, read from ``run_steps``' constants at call time (the tests
    patch them there, for ``hub run`` and ``hub ship`` alike)."""
    return StepTimeouts(
        gate=run_steps.GATE_TIMEOUT,
        push=run_steps.PUSH_TIMEOUT,
        gh=run_steps.GH_TIMEOUT,
        git=run_steps.GIT_TIMEOUT,
    )


def ship_child(worktree: Path) -> ChildCall:
    """``pr_steps``' child runner for ``worktree``: the program found on the environment's
    ``PATH``, run in the caller's group; a child that cannot start or times out is a
    ``PrStepError``."""

    def child(
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        output_limit: int = run_steps.CHILD_OUTPUT_LIMIT,
        cwd: Path | None = None,
    ) -> ChildResult:
        name = argv[0]
        program = shutil.which(name, path=env.get("PATH", ""))
        if program is None:
            raise PrStepError(f"{name} is not on PATH")
        try:
            return run_child(
                [os.path.abspath(program), *argv[1:]],
                cwd=worktree if cwd is None else cwd,
                env=env,
                timeout=timeout,
                own_session=False,
                output_limit=output_limit,
            )
        except ChildTimedOutError:
            raise PrStepError(f"{name} timed out after {timeout:g} s") from None
        except OSError as error:
            raise PrStepError(f"{name} could not run: {error.strerror or error}") from None

    return child


def _refuse_uncommitted(run: ShipRun, *, after: str) -> None:
    # As hub run's gate: the PR holds the commits only, so no tracked change may sit beside them.
    timeout = step_timeouts().git
    for target in run.targets:
        try:
            refuse_uncommitted(ship_child(target.worktree), environ=run.environ, timeout=timeout)
        except PrStepError as error:
            fail(f"{PREFIX}: {target.repo}: {error.reason}", after)


def _heads(run: ShipRun, target: ShipTarget) -> str:
    """The worktree's HEAD and its task branch's commit, as git prints them."""
    try:
        return git_output(
            ship_child(target.worktree),
            *("rev-parse", "HEAD", f"refs/heads/{target.branch}"),
            environ=run.environ,
            timeout=step_timeouts().git,
        )
    except PrStepError as error:
        fail(f"{PREFIX}: {target.repo}: {error.reason}", NOTHING_PUSHED)


def check_log_path(hub: Path, *, issue_id: str, repo: str) -> Path:
    """Where the check of ``repo`` for ``issue_id`` writes its output."""
    return hub.joinpath(*LOG_FOLDERS, f"{issue_id}-{repo}.log")


def _check(run: ShipRun, target: ShipTarget) -> str:
    """Run the target's check with its log opened first: a log that cannot be opened stops the
    ship before the check runs. The log gets the stdout tail, then the stderr tail (E7). Returns
    the heads the check ran on (``_heads``)."""
    path = check_log_path(run.hub, issue_id=run.issue.id, repo=target.repo)
    shown_log = shown_path(str(path))
    descriptor = _opened_log(run.hub, path.name, repo=target.repo, shown_log=shown_log)
    with os.fdopen(descriptor, "wb") as log:
        heads = _heads(run, target)
        output, failure = _run_check(run, target)
        try:
            log.write(output)
            log.flush()
        except OSError as error:
            fail(
                f"{PREFIX}: {target.repo}: cannot write the check log {shown_log}:"
                f" {error.strerror or error}",
                NOTHING_PUSHED,
            )
    if failure is not None:
        fail(f"{PREFIX}: {target.repo}: {failure}; output in {shown_log}", NOTHING_PUSHED)
    typer.echo(f"check passed: {target.repo}")
    return heads


def _run_check(run: ShipRun, target: ShipTarget) -> tuple[bytes, str | None]:
    """The check's log text, and why it failed (None when it passed)."""
    shown = target.check[: run_steps.MAX_GATE_SHOWN_CHARS]
    try:
        result = run_gate(
            ship_child(target.worktree),
            gate=target.check,
            environ=run.environ,
            timeout=step_timeouts().gate,
        )
    except PrStepError as error:
        return f"--- {error.reason} ---\n".encode(errors="replace"), (
            f"check failed ({shown}): {error.reason}"
        )
    failure = None if result.returncode == 0 else f"check failed ({shown})"
    return _log_text(result), failure


def _opened_log(hub: Path, name: str, *, repo: str, shown_log: str) -> int:
    """The log ``name`` opened in ``<hub>/.agent-runs/ship``, walked by folder descriptor: each
    folder made owner-only when absent, never followed through a link, and the file never
    opened through one (emptied when it exists)."""
    opened: list[int] = []
    try:
        opened.append(os.open(hub, _FOLDER_FLAGS))
        for folder in LOG_FOLDERS:
            with contextlib.suppress(FileExistsError):
                os.mkdir(folder, _PRIVATE_FOLDER, dir_fd=opened[-1])
            opened.append(os.open(folder, _FOLDER_FLAGS | os.O_NOFOLLOW, dir_fd=opened[-1]))
        descriptor = os.open(name, _LOG_FLAGS, _PRIVATE_FILE, dir_fd=opened[-1])
    except OSError as error:
        fail(
            f"{PREFIX}: {repo}: cannot open the check log {shown_log}: {error.strerror or error}",
            NOTHING_PUSHED,
        )
    finally:
        for folder_descriptor in opened:
            os.close(folder_descriptor)
    try:
        os.fchmod(descriptor, _PRIVATE_FILE)
    except OSError as error:
        os.close(descriptor)
        fail(
            f"{PREFIX}: {repo}: cannot open the check log {shown_log}: {error.strerror or error}",
            NOTHING_PUSHED,
        )
    return descriptor


def _log_text(result: ChildResult) -> bytes:
    stdout = result.stdout
    if stdout and not stdout.endswith(b"\n"):
        stdout += b"\n"
    return b"--- stdout ---\n" + stdout + b"--- stderr ---\n" + result.stderr


def _open_prs(run: ShipRun) -> tuple[str, ...]:
    """Per target, in order: push, then open or find its PR; the PRs' urls."""
    urls: list[str] = []
    for target in run.targets:
        try:
            urls.append(_push_and_open(run, target))
        except _StepError as error:
            fail(
                f"{PREFIX}: {target.repo}: {error.step} failed: {error.reason}",
                *(f"{PREFIX}: PR open: {url}" for url in urls),
                NOT_LINKED,
            )
    return tuple(urls)


def _push_and_open(run: ShipRun, target: ShipTarget) -> str:
    child = ship_child(target.worktree)
    timeouts = step_timeouts()
    pr_target = PrTarget(github=target.github, base_branch=target.base, branch=target.branch)
    try:
        push_branch(child, target=pr_target, environ=run.environ, timeouts=timeouts)
    except PrStepError as error:
        raise _StepError(PUSH_STEP, error.reason) from None
    try:
        # The newest commit's subject, as hub run's (spec Q-1).
        subject = git_output(
            child, "log", "-1", "--format=%s", environ=run.environ, timeout=timeouts.git
        )
        opened = open_or_find_pr(
            child,
            target=pr_target,
            title=_title(run, target, subject),
            body=ship_body(issue_id=run.issue.id, issue_url=run.issue.url),
            draft=run.draft,
            environ=run.environ,
            timeout=timeouts.gh,
        )
    except PrStepError as error:
        raise _StepError(PR_STEP, error.reason) from None
    typer.echo(f"{'found' if opened.found else 'opened'}: {target.repo}  {opened.url}")
    return opened.url


def _title(run: ShipRun, target: ShipTarget, subject: str) -> str:
    """The PR title, following the repo's conventions; one warning when ``commit_title`` does
    not match the subject (as hub run's E12)."""
    conventions = target.conventions
    titled = titled_pr(
        subject, conventions=conventions, issue_id=run.issue.id, workspace=str(run.hub.parent)
    )
    if titled.unmatched is not None:
        warning = unmatched_warning(
            PREFIX, line=titled.unmatched, commit_title=conventions.commit_title
        )
        typer.echo(warning, err=True)
    return titled.title
