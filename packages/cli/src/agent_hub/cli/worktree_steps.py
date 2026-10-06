"""The steps of ``hub worktree``, shared with ``hub run``: they raise instead of exiting (E18).

``worktree_task`` checks a task's inputs; ``create_worktree`` and ``remove_worktree`` act on one
repo. A usage problem raises ``WorktreeUsageError``, any other problem ``WorktreeError``, whose
text is what ``hub worktree`` prints after its ``hub worktree:`` prefix. Every git call runs in
the caller's process group, with ``git_timeout`` seconds each (``None``: no limit, as
``hub worktree`` runs); past it ``ChildTimedOutError`` is raised. The repo's setup and teardown
scripts run untimed through ``stream_child``, also in the caller's group.
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

COMMAND: Final = "worktree"
WORKTREES_FOLDER: Final = Path(".claude", "worktrees")
SETUP_SCRIPT: Final = "scripts/worktree-setup.sh"
TEARDOWN_SCRIPT: Final = "scripts/worktree-teardown.sh"
_FETCH_HINT: Final = "; check the network and the remote"
_CLONE_HINT: Final = "clone it next to the hub"
_DIRTY: Final = "it has modified or untracked files"

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
    """One task's checked inputs: the name, the branch, each repo's base and the repos to touch.

    ``bases`` maps each of ``repos`` to ``origin/<its default branch>``.
    """

    name: str
    branch: str
    bases: dict[str, str]
    workspace: Path
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
    """The task named ``name`` in the hub's repos (or ``only``) on ``<branch_prefix><name>``,
    its inputs checked.

    ``runner`` runs every git call of the task; ``env`` is the environment of every git call
    and script but the fetch, which gets ``fetch_env`` (by default ``env``); ``add_options``
    go before ``worktree add`` and ``fetch_options`` before ``fetch``. Raises
    ``WorktreeUsageError`` for a name not shaped like the issue, a branch git refuses or an
    unknown ``only``.
    """
    problem = worktree_name_problem(name, teams=config.tracker.team_keys)
    if problem is not None:
        raise WorktreeUsageError(problem)
    branch = worktree_branch(name, prefix=branch_prefix)
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
    dirs = tuple(repo.dir for repo in config.repos)
    if only is not None and only not in dirs:
        raise WorktreeUsageError(
            f"unknown repo in --only: {shown_path(only)}; use one of: {' '.join(dirs)}"
        )
    repos = dirs if only is None else (only,)
    return WorktreeTask(
        name=name,
        branch=branch,
        bases={repo: f"origin/{config.default_branch_for(repo)}" for repo in repos},
        workspace=hub.parent,
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
    has_branch = _git(
        task, checkout, ("show-ref", "--verify", "-q", f"refs/heads/{task.branch}"), repo=repo
    )
    add: tuple[str, ...]
    if has_branch.returncode == 0:
        add = (*task.add_options, "worktree", "add", "-q", str(worktree), task.branch)
    else:
        add = (*task.add_options, "worktree", "add", "-q", "-b", task.branch)
        add += (str(worktree), task.bases[repo])
    _git_or_raise(task, checkout, add, repo=repo, step="could not add the worktree")
    echo(f"created  {shown_path(str(worktree))} ({task.branch} from {task.bases[repo]})")
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


def _run_script(task: WorktreeTask, repo: str, worktree: Path, *, script: str, echo: Echo) -> None:
    """Run the repo's ``script`` with argv ``[<worktree>]`` when it is an executable file."""
    path = worktree / script
    if not _is_executable_file(path):
        return

    def show(line: bytes) -> None:
        text = line.removesuffix(b"\n").removesuffix(b"\r").decode(errors="replace")
        echo(f"  {repo}: {text}")

    try:
        code = stream_child([str(path), str(worktree)], cwd=worktree, env=task.env, on_line=show)
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
