"""``hub start``'s use case: from a tracker issue to its worktrees, its started state and a session.

The order is the spec's (D-order): read the issue; list every hub repo's task folders and decide
the task name (D-resume); prepare the name (branch checks, before any create); create the
touched repos' missing worktrees; move the issue to the started state; launch. The move is the
last write, so a failure before it never leaves the issue started without its worktrees. A fresh
start moves the issue unconditionally; a resume moves it only while it is unstarted
(``only_if_unstarted``), so an issue already started, in review or closed is left as it is.

A task is resumed when any hub repo, touched or not, holds a worktree of the issue: its name is
kept, and only the touched repos get a worktree. A name read back from disk must be a valid task
name (``task_folder_problem``) before it reaches a prompt, a line shown or a branch.

Every failure becomes a ``StartFailure`` naming the worktrees this run created and the exact
``./hub worktree --remove`` lines that drop them; the worktrees themselves are kept.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from agent_hub.core.errors import AgentHubError, TrackerError
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.tracker.tracker_client import Issue, TrackerClient
from agent_hub.core.workspace.start_prompt import start_prompt
from agent_hub.core.workspace.task_slug import task_folder_problem, task_name


class StartStepError(AgentHubError):
    """A step of ``hub start`` failed; the message is one line naming what and why.

    ``made`` is True when the step's worktree folder exists now and did not before (a setup
    script that failed after ``git worktree add``), so it counts as created.
    """

    def __init__(self, message: str, *, made: bool = False) -> None:
        self.made = made
        # Folder names come from disk: escape what is not printable, as TrackerError does.
        super().__init__(one_line(message))


class AmbiguousTaskError(StartStepError):
    """The hub repos hold the worktrees of more than one task for the issue."""


class TaskWorktrees(Protocol):
    """The task worktrees of the hub repos, in ``hub.json`` order."""

    def task_folders(self, issue_id: str, repos: Sequence[str]) -> Mapping[str, Sequence[str]]:
        """Each of ``repos``' worktree folder names that ``is_task_folder`` gives to ``issue_id``.

        ``start_task`` passes every hub repo, so a task started in other repos is resumed.
        """
        ...

    def prepare(self, name: str) -> None:
        """Check the task's branches for ``name`` before any create; raise ``StartStepError``."""
        ...

    def create(self, repo: str) -> bool:
        """Create ``repo``'s worktree of the prepared task; False when it already exists.

        A failure raises ``StartStepError``, with ``made`` set when the folder was made.
        """
        ...

    def folder(self, repo: str) -> str:
        """The shown path of ``repo``'s worktree of the prepared task."""
        ...


@dataclass(frozen=True, kw_only=True, slots=True)
class StartedTask:
    """A task ready to launch.

    ``repos`` are the touched repos and ``created`` those whose worktree this run created, both
    in ``hub.json`` order. ``resumed`` is True when a worktree of the issue already existed, and
    ``moved`` when this run moved the issue to the started state. ``prompt`` is the session's
    first prompt.
    """

    issue: Issue
    name: str
    repos: tuple[str, ...]
    created: tuple[str, ...]
    resumed: bool
    moved: bool
    prompt: str


class SessionLauncher(Protocol):
    """Starts the session of a task (or, without an agent, shows how to)."""

    def launch(self, task: StartedTask) -> None:
        """Launch the session of ``task``."""
        ...


@dataclass(frozen=True, kw_only=True, slots=True)
class StartFailure:
    """Why ``hub start`` stopped, and what it leaves behind.

    ``name`` is the task name, None when the run stopped before deciding it. ``created`` holds
    the shown path of each worktree this run created, and ``remove`` the lines that drop them.
    """

    reason: str
    name: str | None
    created: tuple[str, ...]
    remove: tuple[str, ...]


def resume_name(found: Mapping[str, Sequence[str]], *, fresh: str) -> tuple[str, bool]:
    """The task name and whether it resumes a task, from each repo's matching folder names.

    No match anywhere gives ``(fresh, False)``; one name, in one or more repos, gives
    ``(name, True)``. Two names in one repo, or different names across repos, raise
    ``AmbiguousTaskError`` naming every match.
    """
    matches = {repo: tuple(names) for repo, names in found.items() if names}
    names = {name for repo_names in matches.values() for name in repo_names}
    if not names:
        return fresh, False
    if len(names) == 1 and all(len(repo_names) == 1 for repo_names in matches.values()):
        return names.pop(), True
    listed = "; ".join(f"{repo}: {', '.join(repo_names)}" for repo, repo_names in matches.items())
    msg = (
        f"worktrees of more than one task match the issue ({listed}); keep one task's"
        " worktrees and remove the others with ./hub worktree --remove <name> --only <repo>"
    )
    raise AmbiguousTaskError(msg)


def remove_commands(
    name: str, *, created: Sequence[str], all_repos: Sequence[str]
) -> tuple[str, ...]:
    """The ``./hub worktree --remove`` lines that drop the ``created`` repos' worktrees.

    One line without ``--only`` when every hub repo was created, else one ``--only`` line per
    created repo; none when nothing was created.
    """
    if not created:
        return ()
    if set(all_repos) <= set(created):
        return (f"./hub worktree --remove {name}",)
    return tuple(f"./hub worktree --remove {name} --only {repo}" for repo in created)


def start_task(
    issue_id: str,
    *,
    repos: Sequence[str],
    all_repos: Sequence[str],
    started_state: str,
    tracker: TrackerClient,
    worktrees: TaskWorktrees,
    launcher: SessionLauncher,
) -> StartFailure | None:
    """Start or resume the task of ``issue_id`` in ``repos``; None once it was launched.

    ``all_repos`` are every hub repo: their task folders decide the name (D-resume), and they
    decide whether a remove line needs ``--only``. Worktrees are created only in ``repos``.
    ``started_state`` is the state a fresh start, or a resume of an unstarted issue, moves to.
    """
    try:
        issue = tracker.get_issue(issue_id)
    except TrackerError as error:
        return StartFailure(reason=str(error), name=None, created=(), remove=())
    try:
        found = worktrees.task_folders(issue_id, all_repos)
        _check_names(found, issue_id)
        name, resumed = resume_name(found, fresh=task_name(issue_id, issue.title))
    except StartStepError as error:
        return StartFailure(reason=str(error), name=None, created=(), remove=())
    created: list[str] = []
    try:
        worktrees.prepare(name)
        for repo in repos:
            _create(worktrees, repo, created)
        # The last write: a resume moves only an issue no one has started (Q-1).
        moved = tracker.move_state(issue_id, started_state, only_if_unstarted=resumed)
    except (StartStepError, TrackerError) as error:
        return StartFailure(
            reason=str(error),
            name=name,
            created=tuple(worktrees.folder(repo) for repo in created),
            remove=remove_commands(name, created=created, all_repos=all_repos),
        )
    launcher.launch(
        StartedTask(
            issue=issue,
            name=name,
            repos=tuple(repos),
            created=tuple(created),
            resumed=resumed,
            moved=moved,
            prompt=start_prompt(issue, task=name),
        )
    )
    return None


def _create(worktrees: TaskWorktrees, repo: str, created: list[str]) -> None:
    # A folder made before the failure (a setup script that failed after the add) is created.
    try:
        if worktrees.create(repo):
            created.append(repo)
    except StartStepError as error:
        if error.made:
            created.append(repo)
        raise


def _check_names(found: Mapping[str, Sequence[str]], issue_id: str) -> None:
    for repo, names in found.items():
        for name in names:
            problem = task_folder_problem(name, issue_id)
            if problem is not None:
                raise StartStepError(f"{repo}: {problem}")
