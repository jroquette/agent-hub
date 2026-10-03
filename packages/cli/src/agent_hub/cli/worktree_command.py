"""``hub worktree``: matching, isolated worktrees for one task in the repos of the hub.

The hub is ``AGENT_HUB_ROOT`` or the cwd; run from a worktree of the hub repo, the main checkout
is the hub (its ``hub.json``, its workspace). Each repo ``<ws>/<dir>`` gets
``<dir>/.claude/worktrees/<name>`` on the branch ``<prefix><name>``, from a freshly fetched
``origin/<default_branch>`` (an existing branch is checked out as it is), then runs the repo's
executable ``scripts/worktree-setup.sh <worktree>``; ``--remove`` runs ``worktree-teardown.sh``
the same way, then ``git worktree remove`` (never forced; branches are kept). Usage problems (the
name, ``--only``) exit 2 before git runs in any repo; a repo problem, or a script that fails,
exits 1 when it is reached, and later repos are left alone. A worktree with modified or
untracked files is never torn down. Git and the scripts run with no timeout in the caller's
process group, so Ctrl-C reaches them. The scripts run with the worktree as their cwd and git's
location variables dropped. The steps themselves are ``worktree_steps``, shared with ``hub run``.
The prefix is the developer's: the main checkout's ``hub.local.json``, else ``hub.json``, else
derived from git's ``user.email`` there; with none, or a malformed local file, it exits 2.
"""

import os
import shutil
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.child_process import git_env, run_child
from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import effective_with_prefix_or_fail
from agent_hub.cli.errors import WorktreeError, WorktreeUsageError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit, main_checkout
from agent_hub.cli.worktree_steps import (
    COMMAND,
    WorktreeTask,
    create_worktree,
    remove_worktree,
    worktree_task,
)

_PREFIX: Final = f"hub {COMMAND}"


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
    _, prefix = effective_with_prefix_or_fail(context, config, home=hub)
    try:
        # This module's run_child, looked up now, runs every git call of the task.
        task = worktree_task(
            config,
            name=name,
            branch_prefix=prefix,
            only=only,
            hub=hub,
            git=git,
            env=env,
            git_timeout=None,
            runner=run_child,
        )
    except WorktreeUsageError as error:
        context.fail(str(error))
    try:
        for repo in task.repos:
            if remove:
                remove_worktree(task, repo, echo=typer.echo)
            else:
                create_worktree(task, repo, echo=typer.echo)
    except WorktreeError as error:
        fail(f"{_PREFIX}: {error}")
    if not remove:
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


def _summary(task: WorktreeTask) -> list[str]:
    remove = f"./hub {COMMAND} --remove {task.name}"
    if task.only is not None:
        remove += f" --only {task.only}"
    return [
        "",
        f"task     : {task.name} (branch {task.branch})",
        f"repos    : {' '.join(task.repos)}",
        f"remove   : {remove}",
    ]
