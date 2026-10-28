"""``hub worktree``: matching, isolated worktrees for one task in the repos of the hub.

The hub is ``AGENT_HUB_ROOT`` or the cwd; run from a worktree of the hub repo, the main checkout is
the hub (its ``hub.json``, its workspace). Each repo ``<ws>/<dir>`` gets
``<dir>/.claude/worktrees/<name>`` on its task branch (``<prefix><name>``, unless ``hub.json``'s
``conventions`` set another ``branch`` pattern for it), from a freshly fetched
``origin/<default_branch>`` (an existing branch is checked out as it is; ``--no-fetch`` skips the
fetch and starts from ``origin/<default_branch>`` as already fetched, refusing a repo where it never
was: the escape hatch inside the Claude Code sandbox, AGH-134; ``--base <branch>`` starts a new
worktree from ``origin/<branch>`` instead, to stack a task on a blocker still in review), then runs
the repo's executable ``scripts/worktree-setup.sh <worktree>``; ``--stack-on <PR url>`` starts
only the pull request's repo (``hub.json``'s ``github``) from its head branch, read with
``gh pr view`` (open and not from a fork), and every other repo from its default branch
(``stack_on``); ``--remove`` runs
``worktree-teardown.sh`` the same way, then ``git worktree remove`` (never forced; branches are
kept). Usage problems (the name, ``--only``, ``--no-fetch``, ``--base`` or ``--stack-on`` with
``--remove``, ``--base`` with ``--stack-on``, a URL that is not one of the hub's repos)
exit 2 before git runs in any repo; a task branch that clashes with a worktree (``check_branches``)
exits 1 before any repo is touched; another repo
problem, or a script that fails, exits 1 when it is reached, and later repos are left alone. A
worktree with modified or untracked files is never torn down. Git and the scripts run with no
timeout in the caller's process group, so Ctrl-C reaches them. The scripts run with the worktree as
their cwd and git's location variables dropped; they also get ``HUB_WORKTREE_NAME``,
``HUB_WORKTREE_BRANCH``, ``HUB_REPO_DIR``, ``HUB_HUB_DIR``, ``HUB_WORKTREE_SLOT`` and
``HUB_PORT_OFFSET`` (see ``docs/design/worktree-environment.md``). The steps themselves are
``worktree_steps``, shared with ``hub run``.
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
from agent_hub.cli.stack_on import stack_base
from agent_hub.cli.worktree_steps import (
    COMMAND,
    StackBase,
    WorktreeTask,
    check_branches,
    create_worktree,
    remove_worktree,
    worktree_task,
)
from agent_hub.core.hub_config.model import HubConfig

_PREFIX: Final = f"hub {COMMAND}"


def worktree(
    context: typer.Context,
    name: Annotated[
        str,
        typer.Argument(metavar="NAME", help="The task: the tracker issue, <team>-<n>[-<desc>]."),
    ],
    *,
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only",
            metavar="REPO",
            help="Touch only this repo (its dir in hub.json); give it again for each repo.",
        ),
    ] = None,
    remove: Annotated[
        bool,
        typer.Option("--remove", help="Remove the task's worktrees instead (branches are kept)."),
    ] = False,
    no_fetch: Annotated[
        bool,
        typer.Option(
            "--no-fetch",
            help=(
                "Do not fetch: start from origin/<default branch> as already fetched (run a bare"
                " git fetch first; for the Claude Code sandbox)."
            ),
        ),
    ] = False,
    base: Annotated[
        str | None,
        typer.Option(
            "--base",
            metavar="BRANCH",
            help=(
                "Start new worktrees from origin/BRANCH instead of the default branch: build on"
                " a blocker's branch that is still in review."
            ),
        ),
    ] = None,
    stack_on: Annotated[
        str | None,
        typer.Option(
            "--stack-on",
            metavar="PR_URL",
            help=(
                "Start the pull request's repo from its head branch (an open pull request of a"
                " hub.json repo, read with gh) and the other repos from their default branch:"
                " stack a task on a blocker still in review."
            ),
        ),
    ] = None,
) -> None:
    """Create isolated worktrees for one task in the hub's repos, or remove them."""
    _check_options(context, remove=remove, no_fetch=no_fetch, base=base, stack_on=stack_on)
    root = hub_root_or_exit(os.environ, command=COMMAND)
    git = _git_or_exit()
    env = git_env(os.environ, optional_locks=True)
    hub = _main_checkout_or_exit(root, git=git)
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    _, prefix = effective_with_prefix_or_fail(context, config, home=hub)
    stacked = None if stack_on is None else _stack_base_or_exit(context, config, stack_on, hub=hub)
    try:
        # This module's run_child, looked up now, runs every git call of the task.
        task = worktree_task(
            config,
            name=name,
            branch_prefix=prefix,
            only=tuple(only) if only else None,
            hub=hub,
            git=git,
            env=env,
            git_timeout=None,
            runner=run_child,
            fetch=not no_fetch,
            base=base,
            stacked=stacked,
        )
    except WorktreeUsageError as error:
        context.fail(str(error))
    try:
        _act(task, remove=remove)
    except WorktreeError as error:
        fail(f"{_PREFIX}: {error}")
    if not remove:
        for line in _summary(task):
            typer.echo(line)


def _act(task: WorktreeTask, *, remove: bool) -> None:
    """Remove each repo's worktree, or check the branches and create them."""
    if not remove:
        check_branches(task)
    for repo in task.repos:
        if remove:
            remove_worktree(task, repo, echo=typer.echo)
        else:
            create_worktree(task, repo, echo=typer.echo)


def _check_options(
    context: typer.Context, *, remove: bool, no_fetch: bool, base: str | None, stack_on: str | None
) -> None:
    """Exit 2 on options that do not go together, before git runs."""
    if remove and no_fetch:
        context.fail("--no-fetch applies to creating worktrees, not to --remove")
    if remove and base is not None:
        context.fail("--base applies to creating worktrees, not to --remove")
    if remove and stack_on is not None:
        context.fail("--stack-on applies to creating worktrees, not to --remove")
    if base is not None and stack_on is not None:
        context.fail("--base and --stack-on both name the base: pass one")


def _stack_base_or_exit(
    context: typer.Context, config: HubConfig, url: str, *, hub: Path
) -> StackBase:
    """The blocker's repo and branch of ``--stack-on``'s pull request, or the command's exit."""
    gh = shutil.which("gh")
    if gh is None:
        fail(f"{_PREFIX}: --stack-on reads the pull request with gh, which is not on PATH")
    try:
        return stack_base(
            config, url, gh=os.path.abspath(gh), cwd=hub, env=dict(os.environ), runner=run_child
        )
    except WorktreeUsageError as error:
        context.fail(str(error))
    except WorktreeError as error:
        fail(f"{_PREFIX}: {error}")


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
    remove += "".join(f" --only {repo}" for repo in task.only)
    branches = set(task.branches.values())
    if len(branches) == 1:
        (branch,) = branches
        named = [f"task     : {task.name} (branch {branch})"]
    else:
        named = [f"task     : {task.name}"]
        named += [f"branch   : {repo} {task.branches[repo]}" for repo in task.repos]
    return ["", *named, f"repos    : {' '.join(task.repos)}", f"remove   : {remove}"]
