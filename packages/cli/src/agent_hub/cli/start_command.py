"""``hub start ISSUE``: a tracker issue to its worktrees, its started state and a Claude session.

The hub is ``AGENT_HUB_ROOT`` or the cwd; run from a worktree of the hub repo, its main checkout
is the hub (its ``hub.json``, its workspace, the session's cwd). Usage problems exit 2 before any
tracker call or git call in a repo: an issue not shaped ``<TEAM>-<n>`` (uppercase) for a team of
``hub.json``, a ``--repo`` that is not a repo ``dir`` of ``hub.json``, a malformed
``hub.local.json`` or no branch prefix. Then, without ``--no-agent``, ``claude`` must be on
``PATH``, and transport ``api`` needs ``LINEAR_API_KEY`` (exit 1, before any request).

The use case is core's ``start_task`` (D-order): read the issue, find its task worktrees in every
hub repo (a found name resumes the task), check the branches, create the touched repos' missing
worktrees (``hub worktree``'s steps), move the issue to ``tracker.states.started`` (a resume
moves only an unstarted issue), then launch: ``claude`` exec'd from the hub's main checkout with
the task's worktrees attached, a per-task context file
(``brain/auto/agent-context-<issue id lower>.md``) and the issue as the first prompt. With
``--no-agent`` the summary ends with the command that resumes and launches. A failure prints
``hub start: <reason>``, each worktree this run created and the lines that remove them, and
exits 1; the worktrees are kept.
"""

import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.child_process import git_env, run_child
from agent_hub.cli.claude_launch import claude_missing_line, launch_claude
from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import effective_with_prefix_or_fail
from agent_hub.cli.errors import LaunchError, WorktreeError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit, local_home
from agent_hub.cli.init_report import shown_path
from agent_hub.cli.run_children import CHILD_HIDDEN, SESSION_HIDDEN, without
from agent_hub.cli.tracker_client import missing_key_line, resolve_tracker_client, transport_line
from agent_hub.cli.worktree_steps import (
    WORKTREES_FOLDER,
    WorktreeTask,
    check_branches,
    create_worktree,
    task_folders,
    worktree_task,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.team_keys import team_of, teams_text
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN
from agent_hub.core.workspace.agent_launch import CLAUDE
from agent_hub.core.workspace.start_task import (
    StartedTask,
    StartFailure,
    StartStepError,
    remove_commands,
    start_task,
)

COMMAND: Final = "start"
_PREFIX: Final = f"hub {COMMAND}"
_CONTEXT_FILE: Final = "brain/auto/agent-context-{issue}.md"


def start(
    context: typer.Context,
    issue: Annotated[
        str, typer.Argument(metavar="ISSUE", help="The tracker issue, <TEAM>-<n> (DEM-7).")
    ],
    *,
    repo: Annotated[
        list[str] | None,
        typer.Option(
            "--repo",
            metavar="DIR",
            help="A repo to work in (its dir in hub.json); repeatable. Default: every repo.",
        ),
    ] = None,
    no_agent: Annotated[
        bool,
        typer.Option("--no-agent", help="Stop before the session; print how to launch it."),
    ] = False,
) -> None:
    """Start or resume an issue: its worktrees, its started state and a Claude Code session."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    # No token reaches git, which only looks for the main checkout.
    hub = local_home(root, environ=without(os.environ, SESSION_HIDDEN))
    hub_config = load_hub_config_or_exit(hub / FILE_LABEL)
    touched = _refuse_usage(context, hub_config, issue=issue, repos=repo)
    effective, prefix = effective_with_prefix_or_fail(context, hub_config, home=hub)
    config = effective.config
    if not no_agent and shutil.which(CLAUDE) is None:
        fail(claude_missing_line(COMMAND))
    missing = missing_key_line(config, os.environ, command=COMMAND)
    if missing is not None:
        fail(missing)
    typer.echo(transport_line(config), err=True)
    all_repos = tuple(entry.dir for entry in config.repos)
    worktrees = GitTaskWorktrees(
        config, hub=hub, git=_git_or_exit(), branch_prefix=prefix, repos=touched
    )
    client = resolve_tracker_client(config, os.environ, hub_root=hub)
    session = Session(
        hub=hub,
        worktrees=worktrees,
        all_repos=all_repos,
        started_state=config.tracker.states.started,
        flags=() if repo is None else touched,
    )
    failure = start_task(
        issue,
        repos=touched,
        all_repos=all_repos,
        started_state=config.tracker.states.started,
        tracker=client,
        worktrees=worktrees,
        launcher=PrintedSession(session) if no_agent else ClaudeSession(session),
    )
    if failure is not None:
        fail(*_failure_lines(failure))


class GitTaskWorktrees:
    """``start_task``'s ``TaskWorktrees`` over ``hub worktree``'s steps.

    ``prepare`` builds the task over the touched ``repos`` and checks their branches before any
    create; every ``WorktreeError`` becomes a ``StartStepError`` with the same text.
    """

    def __init__(
        self,
        config: HubConfig,
        *,
        hub: Path,
        git: str,
        branch_prefix: str,
        repos: Sequence[str],
    ) -> None:
        self._config = config
        self._hub = hub
        self._git = git
        self._prefix = branch_prefix
        self._repos = tuple(repos)
        self._task: WorktreeTask | None = None

    @property
    def task(self) -> WorktreeTask:
        """The prepared task; ``prepare`` must have succeeded."""
        if self._task is None:
            msg = "prepare the task first"
            raise RuntimeError(msg)
        return self._task

    def task_folders(self, issue_id: str, repos: Sequence[str]) -> Mapping[str, Sequence[str]]:
        try:
            return task_folders(self._hub.parent, repos, issue_id)
        except WorktreeError as error:
            raise StartStepError(str(error)) from None

    def prepare(self, name: str) -> None:
        try:
            task = worktree_task(
                self._config,
                name=name,
                branch_prefix=self._prefix,
                only=None,
                hub=self._hub,
                git=self._git,
                # The scripts are the repo's: they never get the tracker key.
                env=git_env(without(os.environ, CHILD_HIDDEN), optional_locks=True),
                git_timeout=None,
                runner=run_child,
                repos=self._repos,
            )
            check_branches(task)
        except WorktreeError as error:
            raise StartStepError(str(error)) from None
        self._task = task

    def create(self, repo: str) -> bool:
        path = self.path(repo)
        existed = path.is_dir()
        try:
            create_worktree(self.task, repo, echo=typer.echo)
        except WorktreeError as error:
            raise StartStepError(str(error), made=not existed and path.is_dir()) from None
        return not existed

    def folder(self, repo: str) -> str:
        return shown_path(str(self.path(repo)))

    def path(self, repo: str) -> Path:
        """``repo``'s worktree of the prepared task."""
        return self.task.workspace / repo / WORKTREES_FOLDER / self.task.name


class Session:
    """What both launchers show: the task's summary lines and the command that resumes it."""

    def __init__(
        self,
        *,
        hub: Path,
        worktrees: GitTaskWorktrees,
        all_repos: Sequence[str],
        started_state: str,
        flags: Sequence[str],
    ) -> None:
        self.hub = hub
        self.worktrees = worktrees
        self.all_repos = tuple(all_repos)
        self.started_state = started_state
        self.flags = tuple(flags)

    def summary(self, task: StartedTask) -> list[str]:
        """The lines after the ``created``/``exists`` lines: task, repos, worktrees, state,
        remove."""
        branches = self.worktrees.task.branches
        distinct = set(branches.values())
        if len(distinct) == 1:
            (branch,) = distinct
            named = [f"task     : {task.name} (branch {branch})"]
        else:
            named = [f"task     : {task.name}"]
            named += [f"branch   : {repo} {branches[repo]}" for repo in task.repos]
        removes = remove_commands(task.name, created=task.repos, all_repos=self.all_repos)
        return [
            "",
            *named,
            f"repos    : {' '.join(task.repos)}",
            *(f"worktree : {self.worktrees.folder(repo)}" for repo in task.repos),
            f"state    : {self._state(task)}",
            *(f"remove   : {line}" for line in removes),
        ]

    def next_command(self, issue_id: str) -> str:
        """The command that resumes the task and launches its session: the same ``--repo``s."""
        return " ".join([f"./hub {COMMAND} {issue_id}", *(f"--repo {repo}" for repo in self.flags)])

    def _state(self, task: StartedTask) -> str:
        if task.moved:
            return self.started_state
        return f"{task.issue.state} (already started, not moved)"


class ClaudeSession:
    """Prints the summary, then execs ``claude`` from the hub's main checkout (D-launch)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def launch(self, task: StartedTask) -> None:
        session = self._session
        for line in session.summary(task):
            typer.echo(line)
        folders = [
            (f"{repo}/{WORKTREES_FOLDER}/{task.name}", session.worktrees.path(repo))
            for repo in task.repos
        ]
        context_file = session.hub / _CONTEXT_FILE.format(issue=task.issue.id.lower())
        try:
            os.chdir(session.hub)
            launch_claude(
                hub=session.hub, folders=folders, context_file=context_file, extra=[task.prompt]
            )
        except (LaunchError, OSError) as error:
            fail(*self._launch_failure(task, error))

    def _launch_failure(self, task: StartedTask, error: Exception) -> list[str]:
        session = self._session
        reason = (
            str(error)
            if isinstance(error, LaunchError)
            else f"cannot enter {shown_path(str(session.hub))}: {_strerror(error)}"
        )
        lines = [f"{_PREFIX}: {reason}"]
        if task.moved:
            lines.append(
                f"state    : {task.issue.id} was moved to {session.started_state};"
                f" {session.next_command(task.issue.id)} resumes the task"
            )
        lines += [f"created  : {session.worktrees.folder(repo)}" for repo in task.created]
        removes = remove_commands(task.name, created=task.created, all_repos=session.all_repos)
        lines += [f"remove   : {line}" for line in removes]
        return lines


class PrintedSession:
    """``--no-agent``: prints the summary and the command that launches the session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def launch(self, task: StartedTask) -> None:
        for line in self._session.summary(task):
            typer.echo(line)
        typer.echo(f"next     : {self._session.next_command(task.issue.id)}")


def _refuse_usage(
    context: typer.Context, config: HubConfig, *, issue: str, repos: Sequence[str] | None
) -> tuple[str, ...]:
    """The touched repos in ``hub.json`` order; a usage error (exit 2) for a bad issue or dir."""
    teams = config.tracker.team_keys
    if not (ISSUE_ID_PATTERN.fullmatch(issue) and team_of(issue, teams)):
        team = config.tracker.default_team
        if len(teams) == 1:
            context.fail(f"issue must look like {team}-<n> (e.g. {team}-1)")
        context.fail(
            f"issue must look like <TEAM>-<n> (e.g. {team}-1); use one of: {teams_text(teams)}"
        )
    dirs = tuple(entry.dir for entry in config.repos)
    if repos is None:
        return dirs
    unknown = [repo for repo in dict.fromkeys(repos) if repo not in dirs]
    if unknown:
        shown = " ".join(shown_path(repo) for repo in unknown)
        context.fail(f"unknown repo in --repo: {shown}; use one of: {' '.join(dirs)}")
    return tuple(repo for repo in dirs if repo in repos)


def _failure_lines(failure: StartFailure) -> list[str]:
    return [
        f"{_PREFIX}: {failure.reason}",
        *(f"created  : {path}" for path in failure.created),
        *(f"remove   : {line}" for line in failure.remove),
    ]


def _git_or_exit() -> str:
    found = shutil.which("git")
    if found is None:
        fail(f"{_PREFIX}: git is not on PATH; install git")
    # PATH may hold a relative folder, found from the cwd; git runs in other folders.
    return os.path.abspath(found)


def _strerror(error: Exception) -> str:
    return (error.strerror if isinstance(error, OSError) else None) or str(error)
