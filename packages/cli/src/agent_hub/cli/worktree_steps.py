"""The steps of ``hub worktree``, shared with ``hub run``: they raise instead of exiting (E18).

``worktree_task`` checks a task's inputs; ``check_branches`` checks, before anything is
created, that no touched repo's branch clashes with a worktree; ``create_worktree`` and
``remove_worktree`` act on one repo. A usage problem raises ``WorktreeUsageError``, any other
problem ``WorktreeError``, whose text is what ``hub worktree`` prints after its ``hub worktree:``
prefix. Every git call runs in the caller's process group, with ``git_timeout`` seconds each
(``None``: no limit, as ``hub worktree`` runs); past it ``ChildTimedOutError`` is raised. The
repo's setup and teardown scripts run untimed through ``stream_child``, also in the caller's
group, with the task's environment plus the six ``SCRIPT_VARIABLES`` (``script_env``): the
task's name and the repo's branch, the repo's main checkout, the hub's, and the task's port slot
and offset (``worktree_slot``).
"""

import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from agent_hub.cli.child_process import ChildResult, run_child, stream_child
from agent_hub.cli.errors import WorktreeError, WorktreeUsageError
from agent_hub.cli.init_report import shown_path
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.workspace.worktree_name import (
    worktree_branch,
    worktree_name_example,
    worktree_name_problem,
)
from agent_hub.core.workspace.worktree_slot import port_offset, worktree_slot

COMMAND: Final = "worktree"
WORKTREES_FOLDER: Final = Path(".claude", "worktrees")
SETUP_SCRIPT: Final = "scripts/worktree-setup.sh"
TEARDOWN_SCRIPT: Final = "scripts/worktree-teardown.sh"
# What ``script_env`` sets for the scripts, in this order, over the caller's values.
SCRIPT_VARIABLES: Final = (
    "HUB_WORKTREE_NAME",
    "HUB_WORKTREE_BRANCH",
    "HUB_REPO_DIR",
    "HUB_HUB_DIR",
    "HUB_WORKTREE_SLOT",
    "HUB_PORT_OFFSET",
)
_FETCH_HINT: Final = "; check the network and the remote"
_CLONE_HINT: Final = "clone it next to the hub"
_DIRTY: Final = "it has modified or untracked files"
# Each branch with the worktree it is checked out in (empty when none), as git worktree list
# shows them; a "worktree" call of its own would be one more git call before the add.
_WORKTREE_PATHS: Final = "--format=%(refname) %(worktreepath)"

type Echo = Callable[[str], None]


class ChildRunner(Protocol):
    """Runs one git call as ``child_process.run_child`` does; the command passes its own."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str,
        env: Mapping[str, str],
        timeout: float | None,
        own_session: bool | None = None,
    ) -> ChildResult:
        """Run ``argv``; ``ChildTimedOutError`` past ``timeout``, ``OSError`` if it cannot start."""
        ...


@dataclass(frozen=True, kw_only=True, slots=True)
class WorktreeTask:
    """One task's checked inputs: the name, each repo's branch and base, and the repos to touch.

    ``branches`` maps each of ``repos`` to its task branch, ``bases`` to
    ``origin/<its default branch>``.
    """

    name: str
    branches: dict[str, str]
    bases: dict[str, str]
    workspace: Path
    # The hub's main checkout; its scripts get it as HUB_HUB_DIR.
    hub: Path
    repos: tuple[str, ...]
    only: str | None
    git: str
    env: dict[str, str]
    git_timeout: float | None
    runner: ChildRunner
    # The fetch's environment (it may need the network's credentials) and options given to
    # git before "fetch" and before "worktree add"; hub worktree uses ``env`` and none.
    fetch_env: dict[str, str]
    add_options: tuple[str, ...]
    fetch_options: tuple[str, ...]


def worktree_task(
    config: HubConfig,
    *,
    name: str,
    branch_prefix: str,
    only: str | None,
    hub: Path,
    git: str,
    env: dict[str, str],
    git_timeout: float | None,
    runner: ChildRunner = run_child,
    fetch_env: dict[str, str] | None = None,
    add_options: tuple[str, ...] = (),
    fetch_options: tuple[str, ...] = (),
) -> WorktreeTask:
    """The task named ``name`` in the hub's repos (or ``only``), its inputs checked.

    Each repo's branch is ``name`` rendered with the repo's effective ``conventions.branch``
    (``conventions_for``) and ``branch_prefix``; today's ``<branch_prefix><name>`` when nothing
    sets one. The name is checked first, then ``only``, then each distinct branch of the
    touched repos with ``git check-ref-format``, in repo order.

    ``runner`` runs every git call of the task; ``env`` is the environment of every git call
    but the fetch, which gets ``fetch_env`` (by default ``env``), and, with the six
    ``SCRIPT_VARIABLES``, of the scripts (``script_env``); ``add_options``
    go before ``worktree add`` and ``fetch_options`` before ``fetch``. Raises
    ``WorktreeUsageError`` for a name not shaped like the issue, an unknown ``only`` or a
    branch git refuses.
    """
    problem = worktree_name_problem(name, teams=config.tracker.team_keys)
    if problem is not None:
        raise WorktreeUsageError(problem)
    dirs = tuple(repo.dir for repo in config.repos)
    if only is not None and only not in dirs:
        raise WorktreeUsageError(
            f"unknown repo in --only: {shown_path(only)}; use one of: {' '.join(dirs)}"
        )
    repos = dirs if only is None else (only,)
    branches = {
        repo: worktree_branch(
            name, prefix=branch_prefix, pattern=config.conventions_for(repo).branch
        )
        for repo in repos
    }
    for branch in dict.fromkeys(branches.values()):
        checked = runner(
            [git, "check-ref-format", "--branch", branch],
            cwd=hub,
            env=env,
            timeout=git_timeout,
            own_session=False,
        )
        if checked.returncode != 0:
            raise WorktreeUsageError(
                f"git refuses the branch name {shown_path(branch)};"
                f" use a name like {worktree_name_example(config.tracker.default_team)}"
            )
    return WorktreeTask(
        name=name,
        branches=branches,
        bases={repo: f"origin/{config.default_branch_for(repo)}" for repo in repos},
        workspace=hub.parent,
        hub=hub,
        repos=repos,
        only=only,
        git=git,
        env=env,
        git_timeout=git_timeout,
        runner=runner,
        fetch_env=env if fetch_env is None else fetch_env,
        add_options=add_options,
        fetch_options=fetch_options,
    )


def check_branches(task: WorktreeTask) -> None:
    """Refuse, before anything is created, a touched repo whose task branch clashes (E22).

    Its task folder is not a worktree (no ``.git`` entry), its task worktree is on another
    branch, or (with no task worktree yet) the branch is checked out in another worktree, where
    ``git worktree add`` would fail after earlier repos' worktrees were made. A repo that is not
    cloned is left to ``create_worktree``.
    """
    for repo in task.repos:
        checkout = task.workspace / repo
        if not os.path.lexists(checkout / ".git"):
            continue
        branch = task.branches[repo]
        worktree = checkout / WORKTREES_FOLDER / task.name
        if worktree.is_dir():
            _check_worktree_branch(task, repo, worktree, branch=branch)
            continue
        listed = _git(
            task, checkout, ("for-each-ref", _WORKTREE_PATHS, f"refs/heads/{branch}"), repo=repo
        )
        if listed.returncode != 0:
            raise WorktreeError(f"{repo}: could not list the branches: {_first_line(listed)}")
        holder = _checked_out_in(listed.stdout, branch)
        if holder is not None:
            raise WorktreeError(
                f"{repo}: {shown_path(branch)} is already checked out in {shown_path(holder)}"
            )


def _check_worktree_branch(task: WorktreeTask, repo: str, worktree: Path, *, branch: str) -> None:
    """Refuse ``repo``'s existing task folder unless it is a worktree on ``branch``."""
    # Without its .git entry, git would read the checkout's own branch from inside it.
    if not os.path.lexists(worktree / ".git"):
        raise WorktreeError(f"{repo}: {shown_path(str(worktree))} is not a worktree; remove it")
    current = _git(task, worktree, ("branch", "--show-current"), repo=repo)
    if current.returncode != 0:
        raise WorktreeError(
            f"{repo}: could not read the branch of {shown_path(str(worktree))}:"
            f" {_first_line(current)}"
        )
    actual = current.stdout.decode(errors="replace").strip() or "a detached HEAD"
    if actual != branch:
        raise WorktreeError(
            f"{repo}: {shown_path(str(worktree))} is on {shown_path(actual)},"
            f" not {shown_path(branch)}"
        )


def _checked_out_in(listed: bytes, branch: str) -> str | None:
    """The worktree ``branch`` is checked out in, from ``for-each-ref`` with ``_WORKTREE_PATHS``."""
    for line in listed.decode(errors="replace").splitlines():
        ref, _, path = line.partition(" ")
        if ref == f"refs/heads/{branch}" and path:
            return path
    return None


def create_worktree(task: WorktreeTask, repo: str, *, echo: Echo) -> Path:
    """Create ``repo``'s worktree from a fresh fetch (an existing one is kept); its path.

    ``echo`` gets the ``exists``/``created`` line and each line of the setup script.
    """
    checkout = task.workspace / repo
    if not os.path.lexists(checkout / ".git"):
        raise WorktreeError(f"{shown_path(str(checkout))} is not a git checkout; {_CLONE_HINT}")
    worktree = checkout / WORKTREES_FOLDER / task.name
    if worktree.is_dir():
        echo(f"exists   {shown_path(str(worktree))}")
        return worktree
    _git_or_raise(
        task,
        checkout,
        (*task.fetch_options, "fetch", "-q", "origin"),
        repo=repo,
        step="could not fetch origin",
        env=task.fetch_env,
    )
    branch = task.branches[repo]
    has_branch = _git(
        task, checkout, ("show-ref", "--verify", "-q", f"refs/heads/{branch}"), repo=repo
    )
    add: tuple[str, ...]
    if has_branch.returncode == 0:
        add = (*task.add_options, "worktree", "add", "-q", str(worktree), branch)
    else:
        add = (*task.add_options, "worktree", "add", "-q", "-b", branch)
        add += (str(worktree), task.bases[repo])
    _git_or_raise(task, checkout, add, repo=repo, step="could not add the worktree")
    echo(f"created  {shown_path(str(worktree))} ({branch} from {task.bases[repo]})")
    _run_script(task, repo, worktree, script=SETUP_SCRIPT, echo=echo)
    return worktree


def remove_worktree(task: WorktreeTask, repo: str, *, echo: Echo) -> None:
    """Tear down and remove ``repo``'s worktree when it exists; a dirty one is refused."""
    checkout = task.workspace / repo
    worktree = checkout / WORKTREES_FOLDER / task.name
    if not worktree.is_dir():
        return
    # git worktree remove would refuse a dirty worktree, but only after the teardown ran.
    status = _git(task, worktree, ("status", "--porcelain"), repo=repo)
    if status.returncode != 0 or status.stdout:
        reason = _first_line(status) if status.returncode != 0 else _DIRTY
        raise WorktreeError(f"{repo}: could not remove {shown_path(str(worktree))}: {reason}")
    _run_script(task, repo, worktree, script=TEARDOWN_SCRIPT, echo=echo)
    _git_or_raise(
        task,
        checkout,
        ("worktree", "remove", str(worktree)),
        repo=repo,
        step="could not remove the worktree",
    )
    echo(f"removed  {shown_path(str(worktree))}")


def script_env(task: WorktreeTask, repo: str) -> dict[str, str]:
    """The environment of ``repo``'s setup and teardown scripts: ``task.env``, then the six
    ``SCRIPT_VARIABLES``, which override a caller's values of the same names."""
    slot = worktree_slot(task.name)
    return {
        **task.env,
        "HUB_WORKTREE_NAME": task.name,
        "HUB_WORKTREE_BRANCH": task.branches[repo],
        "HUB_REPO_DIR": str(task.workspace / repo),
        "HUB_HUB_DIR": str(task.hub),
        "HUB_WORKTREE_SLOT": str(slot),
        "HUB_PORT_OFFSET": str(port_offset(slot)),
    }


def _run_script(task: WorktreeTask, repo: str, worktree: Path, *, script: str, echo: Echo) -> None:
    """Run the repo's ``script`` with argv ``[<worktree>]`` and ``script_env`` when it is an
    executable file."""
    path = worktree / script
    if not _is_executable_file(path):
        return

    def show(line: bytes) -> None:
        text = line.removesuffix(b"\n").removesuffix(b"\r").decode(errors="replace")
        echo(f"  {repo}: {text}")

    try:
        code = stream_child(
            [str(path), str(worktree)], cwd=worktree, env=script_env(task, repo), on_line=show
        )
    except OSError as error:
        raise WorktreeError(f"{repo}: {script} could not run: {error.strerror or error}") from None
    if code == 0:
        return
    ended = f"was killed by signal {-code}" if code < 0 else f"exited {code}"
    hint = ""
    if script == SETUP_SCRIPT:
        hint = (
            f"; the worktree is kept: run the script again ({shown_path(str(path))}"
            f" {shown_path(str(worktree))}) or remove it with"
            f" ./hub {COMMAND} --remove {task.name} --only {repo}"
        )
    raise WorktreeError(f"{repo}: {script} {ended}{hint}")


def _is_executable_file(path: Path) -> bool:
    # As the shell's [ -x ]: a link is followed; a folder or a FIFO is never run.
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and os.access(path, os.X_OK)


def _git(
    task: WorktreeTask,
    folder: Path,
    arguments: tuple[str, ...],
    *,
    repo: str,
    env: dict[str, str] | None = None,
) -> ChildResult:
    try:
        return task.runner(
            [task.git, *arguments],
            cwd=folder,
            env=task.env if env is None else env,
            timeout=task.git_timeout,
            own_session=False,
        )
    except OSError as error:
        raise WorktreeError(f"{repo}: git could not run: {error.strerror or error}") from None


def _git_or_raise(
    task: WorktreeTask,
    folder: Path,
    arguments: tuple[str, ...],
    *,
    repo: str,
    step: str,
    env: dict[str, str] | None = None,
) -> None:
    result = _git(task, folder, arguments, repo=repo, env=env)
    if result.returncode != 0:
        hint = _FETCH_HINT if "fetch" in arguments else ""
        raise WorktreeError(f"{repo}: {step}: {_first_line(result)}{hint}")


def _first_line(result: ChildResult) -> str:
    lines = [line.strip() for line in result.stderr.decode(errors="replace").splitlines()]
    return next((line for line in lines if line), f"git exited {result.returncode}")
