"""The shipping set of ``hub ship``: the repos whose task worktree for the issue is ahead.

Only ``hub.json``'s repos, the task worktree names (``<team>-<n>[-<desc>]``) and each repo's
branch convention decide it (spec D-set). Git only reads here, with no optional lock (PD-7), so
a dry run leaves every ``.git`` as it was. Every refusal is a ``ShipError`` raised before the
set is returned, so before any check runs (AC-63.5, E8).
"""

import dataclasses
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_hub.cli import run_steps
from agent_hub.cli.child_process import git_env, run_child
from agent_hub.cli.errors import ChildTimedOutError, ShipError
from agent_hub.cli.init_report import shown_path
from agent_hub.cli.pr_steps import error_tail
from agent_hub.cli.run_children import SESSION_HIDDEN, WORKTREES, without
from agent_hub.core.hub_config.conventions import EffectiveConventions
from agent_hub.core.hub_config.model import HubConfig, Repo
from agent_hub.core.workspace.worktree_name import (
    issue_of_worktree,
    task_worktree_names,
    worktree_branch,
)

_GIT_ENTRY = ".git"


@dataclass(frozen=True, kw_only=True, slots=True)
class ShipTarget:
    """A repo's task worktree for the issue: its branch, its base (the repo's default branch,
    compared as ``origin/<base>``) and how many commits it holds beyond that base."""

    repo: str
    worktree: Path
    branch: str
    base: str
    github: str
    check: str
    conventions: EffectiveConventions
    ahead: int


@dataclass(frozen=True, kw_only=True, slots=True)
class ShipSet:
    """The targets to ship (ahead of their base) and the task worktrees skipped (none ahead),
    each in ``hub.json`` order."""

    targets: tuple[ShipTarget, ...]
    skipped: tuple[ShipTarget, ...]


def shipping_set(
    config: HubConfig,
    *,
    workspace: Path,
    issue_id: str,
    branch_prefix: str,
    environ: Mapping[str, str],
) -> ShipSet:
    """The shipping set of ``issue_id`` among ``config``'s repos checked out in ``workspace``.

    Refuses, in this order: a folder of task worktrees that cannot be listed; a repo with more
    than one task worktree; none in any repo; one without a ``.git`` entry; one on another
    branch than its task branch; a git read that fails; none ahead of its base.
    """
    listed = [
        (repo, _task_worktrees(repo, workspace=workspace, issue_id=issue_id, config=config))
        for repo in config.repos
    ]
    _refuse_two_in_a_repo(listed, issue_id=issue_id)
    found = [(repo, worktrees[0]) for repo, worktrees in listed if worktrees]
    if not found:
        repos = ", ".join(repo.dir for repo in config.repos)
        raise ShipError(
            f"no task worktree for {issue_id} in {repos}"
            f" (looked for <repo>/{WORKTREES.as_posix()}/{issue_id.lower()}[-<desc>])"
        )
    for repo, worktree in found:
        _refuse_without_git_entry(repo, worktree)
    planned = [_planned(config, repo, worktree, prefix=branch_prefix) for repo, worktree in found]
    for target in planned:
        _refuse_other_branch(target, environ=environ)
    counted = [dataclasses.replace(target, ahead=_ahead(target, environ)) for target in planned]
    targets = tuple(target for target in counted if target.ahead > 0)
    if not targets:
        bases = ", ".join(f"{target.repo} (origin/{target.base})" for target in counted)
        raise ShipError(f"no repo has commits ahead of its base for {issue_id}: {bases}")
    return ShipSet(
        targets=targets, skipped=tuple(target for target in counted if target.ahead == 0)
    )


def issue_from_cwd(
    cwd: Path, *, workspace: Path, repos: Sequence[str], teams: Sequence[str]
) -> str | None:
    """The issue of the task worktree ``cwd`` is in (its root or a folder below), else None.

    Both sides are compared as real paths; only the worktree folders of ``repos`` count.
    """
    real = Path(os.path.realpath(cwd))
    for repo in repos:
        folder = Path(os.path.realpath(workspace / repo / WORKTREES))
        if real != folder and real.is_relative_to(folder):
            return issue_of_worktree(real.relative_to(folder).parts[0], teams=teams)
    return None


def _task_worktrees(
    repo: Repo, *, workspace: Path, issue_id: str, config: HubConfig
) -> tuple[Path, ...]:
    # A missing folder holds no task worktree; any other listing problem is named.
    folder = workspace / repo.dir / WORKTREES
    try:
        with os.scandir(folder) as entries:
            names = [entry.name for entry in entries if entry.is_dir(follow_symlinks=False)]
    except FileNotFoundError:
        return ()
    except OSError as error:
        raise ShipError(
            f"{repo.dir}: cannot list {shown_path(str(folder))}: {error.strerror or error}"
        ) from None
    names_found = task_worktree_names(names, issue_id=issue_id, teams=config.tracker.team_keys)
    return tuple(folder / name for name in names_found)


def _refuse_two_in_a_repo(
    listed: Sequence[tuple[Repo, tuple[Path, ...]]], *, issue_id: str
) -> None:
    for repo, worktrees in listed:
        if len(worktrees) > 1:
            paths = ", ".join(shown_path(str(worktree)) for worktree in worktrees)
            raise ShipError(
                f"{repo.dir}: more than one task worktree for {issue_id}: {paths};"
                " remove one (hub worktree --remove <name>)"
            )


def _refuse_without_git_entry(repo: Repo, worktree: Path) -> None:
    try:
        os.lstat(worktree / _GIT_ENTRY)
    except OSError:
        raise ShipError(
            f"{repo.dir}: {shown_path(str(worktree))} is not a git worktree:"
            f" it has no {_GIT_ENTRY} entry"
        ) from None


def _planned(config: HubConfig, repo: Repo, worktree: Path, *, prefix: str) -> ShipTarget:
    # Ahead is counted later, once every worktree is known to be on its task branch.
    conventions = config.conventions_for(repo.dir)
    return ShipTarget(
        repo=repo.dir,
        worktree=worktree,
        branch=worktree_branch(worktree.name, prefix=prefix, pattern=conventions.branch),
        base=config.default_branch_for(repo.dir),
        github=repo.github,
        check=repo.check,
        conventions=conventions,
        ahead=0,
    )


def _refuse_other_branch(target: ShipTarget, *, environ: Mapping[str, str]) -> None:
    current = _git_read(target, ("branch", "--show-current"), environ=environ).strip()
    if current != target.branch:
        actual = current or "a detached HEAD"
        raise ShipError(
            f"{target.repo}: {shown_path(str(target.worktree))} is on {actual}, not {target.branch}"
        )


def _ahead(target: ShipTarget, environ: Mapping[str, str]) -> int:
    arguments = ("rev-list", "--count", f"origin/{target.base}..HEAD")
    count = _git_read(target, arguments, environ=environ).strip()
    if not (count.isascii() and count.isdecimal()):
        raise ShipError(
            f"{target.repo}: git rev-list printed no count in {shown_path(str(target.worktree))}"
        )
    return int(count)


def _git_read(target: ShipTarget, arguments: Sequence[str], *, environ: Mapping[str, str]) -> str:
    """git's stdout in the target's worktree, read with no tracker key or GitHub token and no
    optional lock; any failure is a ``ShipError`` naming the repo and the worktree."""
    where = f"in {shown_path(str(target.worktree))}"
    command = f"git {arguments[0]}"
    git = shutil.which("git", path=environ.get("PATH", os.defpath))
    if git is None:
        raise ShipError(f"{target.repo}: git is not on PATH; install git")
    try:
        result = run_child(
            [os.path.abspath(git), *arguments],
            cwd=target.worktree,
            env=git_env(without(environ, SESSION_HIDDEN), optional_locks=False),
            timeout=run_steps.GIT_TIMEOUT,
            own_session=False,
            output_limit=run_steps.CHILD_OUTPUT_LIMIT,
        )
    except ChildTimedOutError:
        raise ShipError(
            f"{target.repo}: {command} timed out after {run_steps.GIT_TIMEOUT:g} s {where}"
        ) from None
    except OSError as error:
        raise ShipError(
            f"{target.repo}: {command} could not run {where}: {error.strerror or error}"
        ) from None
    if result.returncode != 0:
        # One line: git's message may span several.
        tail = " ".join(error_tail(result.stderr).split())
        raise ShipError(f"{target.repo}: {command} failed {where}: {tail}")
    return result.stdout.decode(errors="replace")
