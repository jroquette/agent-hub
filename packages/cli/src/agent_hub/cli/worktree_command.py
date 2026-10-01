"""``hub worktree``: matching, isolated worktrees for one task in the repos of the hub.

The hub is ``AGENT_HUB_ROOT`` or the cwd; run from a worktree of the hub repo, the main checkout
is the hub (its ``hub.json``, its workspace). Each repo ``<ws>/<dir>`` gets
``<dir>/.claude/worktrees/<name>`` on the branch ``<branch_prefix><name>``, from a freshly fetched
``origin/<default_branch>`` (an existing branch is checked out as it is). Usage problems (the
name, ``--only``) exit 2 before git runs in any repo; a repo problem exits 1 when it is reached.
Git runs with no timeout in the caller's process group, so Ctrl-C reaches it.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.child_process import ChildResult, git_env, run_child
from agent_hub.cli.command_exits import fail, not_implemented
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit, main_checkout
from agent_hub.cli.init_report import shown_path
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.workspace.worktree_name import (
    worktree_branch,
    worktree_name_example,
    worktree_name_problem,
)

COMMAND: Final = "worktree"
WORKTREES_FOLDER: Final = Path(".claude", "worktrees")
_PREFIX: Final = f"hub {COMMAND}"
_FETCH_HINT: Final = "; check the network and the remote"
_CLONE_HINT: Final = "clone it next to the hub"


@dataclass(frozen=True, kw_only=True, slots=True)
class _Task:
    """One run's checked inputs: the name, the branch, the base and the repos to touch."""

    name: str
    branch: str
    base: str
    workspace: Path
    repos: tuple[str, ...]
    only: str | None
    git: str
    env: dict[str, str]


def worktree(
    context: typer.Context,
    name: Annotated[
        str,
        typer.Argument(metavar="NAME", help="The task: the tracker issue, <team>-<n>[-<desc>]."),
    ],
    *,
    only: Annotated[
        str | None,
        typer.Option("--only", metavar="REPO", help="Touch only this repo (its dir in hub.json)."),
    ] = None,
    remove: Annotated[
        bool,
        typer.Option("--remove", help="Remove the task's worktrees instead (branches are kept)."),
    ] = False,
) -> None:
    """Create isolated worktrees for one task in the hub's repos, or remove them."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    git = _git_or_exit()
    env = git_env(os.environ, optional_locks=True)
    hub = _main_checkout_or_exit(root, git=git)
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    task = _task_or_refuse(context, config, name=name, only=only, hub=hub, git=git, env=env)
    if remove:
        not_implemented()
    for repo in task.repos:
        _create(task, repo)
    for line in _summary(task):
        typer.echo(line)


def _git_or_exit() -> str:
    found = shutil.which("git")
    if found is None:
        fail(f"{_PREFIX}: git is not on PATH; install git")
    # PATH may hold a relative folder, found from the cwd; git runs in other folders.
    return os.path.abspath(found)


def _main_checkout_or_exit(root: Path, *, git: str) -> Path:
    try:
        return main_checkout(root, git=git, environ=os.environ)
    except OSError as error:
        fail(f"{_PREFIX}: git could not run: {error.strerror or error}")


def _task_or_refuse(
    context: typer.Context,
    config: HubConfig,
    *,
    name: str,
    only: str | None,
    hub: Path,
    git: str,
    env: dict[str, str],
) -> _Task:
    team = config.tracker.team
    problem = worktree_name_problem(name, team=team)
    if problem is not None:
        context.fail(problem)
    branch = worktree_branch(name, prefix=config.project.branch_prefix)
    checked = run_child(
        [git, "check-ref-format", "--branch", branch], cwd=hub, env=env, timeout=None
    )
    if checked.returncode != 0:
        context.fail(
            f"git refuses the branch name {shown_path(branch)};"
            f" use a name like {worktree_name_example(team)}"
        )
    dirs = tuple(repo.dir for repo in config.repos)
    if only is not None and only not in dirs:
        context.fail(f"unknown repo in --only: {shown_path(only)}; use one of: {' '.join(dirs)}")
    return _Task(
        name=name,
        branch=branch,
        base=f"origin/{config.project.default_branch}",
        workspace=hub.parent,
        repos=dirs if only is None else (only,),
        only=only,
        git=git,
        env=env,
    )


def _create(task: _Task, repo: str) -> None:
    checkout = task.workspace / repo
    if not os.path.lexists(checkout / ".git"):
        fail(f"{_PREFIX}: {shown_path(str(checkout))} is not a git checkout; {_CLONE_HINT}")
    worktree = checkout / WORKTREES_FOLDER / task.name
    if worktree.is_dir():
        typer.echo(f"exists   {shown_path(str(worktree))}")
        return
    _git_or_fail(task, checkout, ("fetch", "-q", "origin"), step="could not fetch origin")
    has_branch = _git(task, checkout, ("show-ref", "--verify", "-q", f"refs/heads/{task.branch}"))
    add: tuple[str, ...]
    if has_branch.returncode == 0:
        add = ("worktree", "add", "-q", str(worktree), task.branch)
    else:
        add = ("worktree", "add", "-q", "-b", task.branch, str(worktree), task.base)
    _git_or_fail(task, checkout, add, step="could not add the worktree")
    typer.echo(f"created  {shown_path(str(worktree))} ({task.branch} from {task.base})")


def _summary(task: _Task) -> list[str]:
    remove = f"./hub {COMMAND} --remove {task.name}"
    if task.only is not None:
        remove += f" --only {task.only}"
    return [
        "",
        f"task     : {task.name} (branch {task.branch})",
        f"repos    : {' '.join(task.repos)}",
        f"remove   : {remove}",
    ]


def _git(task: _Task, folder: Path, arguments: tuple[str, ...]) -> ChildResult:
    return run_child([task.git, *arguments], cwd=folder, env=task.env, timeout=None)


def _git_or_fail(task: _Task, folder: Path, arguments: tuple[str, ...], *, step: str) -> None:
    result = _git(task, folder, arguments)
    if result.returncode != 0:
        hint = _FETCH_HINT if arguments[0] == "fetch" else ""
        fail(f"{_PREFIX}: {folder.name}: {step}: {_first_line(result)}{hint}")


def _first_line(result: ChildResult) -> str:
    lines = [line.strip() for line in result.stderr.decode(errors="replace").splitlines()]
    return next((line for line in lines if line), f"git exited {result.returncode}")
