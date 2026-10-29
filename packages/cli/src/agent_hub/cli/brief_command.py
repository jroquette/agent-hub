"""``hub brief``: the session brief (``now.md``, the last journal days, each repo's state, and
the environments of ``hub.json`` and ``hub.local.json`` when they declare any).

The hub is ``AGENT_HUB_ROOT`` or the cwd, and its repos are ``../<dir>``. Git runs in each
checkout with ``GIT_OPTIONAL_LOCKS=0`` and git's location variables dropped, so the brief writes
nothing; ``gh`` runs in the hub. The git and gh calls run at once, in a git pool and a gh
pool of ``MAX_WORKERS`` each (spec Q-4 and Q8), so a hung gh never holds back a git call; the
output keeps the order of ``hub.json``. Every call has a timeout within the brief's one
deadline (a ``gh run list`` it ends shows ``CI: unknown (timeout)``), and stays in the caller's
process group, so the SessionStart hook's kill reaches it; a failed, slow or missing tool only
leaves its value out, as the old script did. The text itself is
``agent_hub.core.workspace.brief_text``.
"""

import datetime
import glob
import os
import re
import shutil
import stat
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated, Final, NamedTuple

import typer

from agent_hub.cli.child_process import git_env, run_child
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.core.hub_config.effective_environments import effective_environments
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.workspace.brief_text import (
    JOURNAL_MAX_AGE,
    BriefInputs,
    RepoState,
    brief_text,
    now_verified,
    select_journal,
)
from agent_hub.core.workspace.environment_lines import brief_block

COMMAND: Final = "brief"
# One deadline for every git and gh call (spec Q8), so the whole brief fits the SessionStart
# hook's 10 s with its resolve step: a call gets what is left, none when nothing is left.
BRIEF_DEADLINE: Final = 2.0
MAX_WORKERS: Final = 8
NOW_PATH: Final = "brain/now.md"
JOURNAL_GLOB: Final = "brain/journal/[0-9]*/[0-9]*/[0-9][0-9].md"
HUB_LINE_NAME: Final = "hub"
_PR_QUERY: Final = '.[] | "#\\(.number) \\(.title)"'
_FAILED_RUNS_QUERY: Final = '.[] | select(.conclusion=="failure") | .name'
_STATUS: Final = ("status", "--porcelain")
# C0 controls but line feed and tab, DEL and C1: a PR title must not move the cursor or recolor.
_CONTROLS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


class GhAnswer(NamedTuple):
    """One gh call's output (empty when it failed) and whether the deadline ended it."""

    text: str
    timed_out: bool


class _Checkout(NamedTuple):
    """A repo the brief shows: its line name, folder, GitHub ``owner/name`` and default branch."""

    name: str
    path: Path
    github: str
    branch: str


def today() -> datetime.date:
    """The day the brief is for: the one clock read (tests replace it)."""
    return datetime.date.today()


def brief(
    *,
    no_network: Annotated[
        bool, typer.Option("--no-network", help="Make no gh call: no PR or CI lines.")
    ] = False,
) -> None:
    """Print the session brief: now.md, the last journal days, each repo's git, PR and CI state."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    loaded = load_effective_config_or_exit(root)
    config = loaded.config
    day = today()
    now_text = _file_text(root / NOW_PATH)
    inputs = BriefInputs(
        now_text=now_text,
        now_age_days=None if now_text is None else _age_days(now_text, day),
        journal=_journal(root, day),
        repos=_repos(root, config, network=not no_network),
        network=not no_network,
        environments=brief_block(effective_environments(config, loaded.local)),
    )
    typer.echo(brief_text(inputs))


def _age_days(now_text: str, day: datetime.date) -> int | None:
    verified = now_verified(now_text)
    if verified is None:
        return None
    try:
        return (day - datetime.date.fromisoformat(verified)).days
    except ValueError:
        # Not a calendar date (2026-02-30): undated, never a crash.
        return None


def _journal(root: Path, day: datetime.date) -> tuple[tuple[str, str], ...]:
    found = glob.glob(os.path.join(glob.escape(str(root)), JOURNAL_GLOB))
    paths = [Path(path).relative_to(root).as_posix() for path in found]
    cutoff = (day - datetime.timedelta(days=JOURNAL_MAX_AGE)).isoformat()
    return tuple(
        (path, _file_text(root / path) or "") for path in select_journal(paths, cutoff=cutoff)
    )


def _file_text(path: Path) -> str | None:
    """A regular file's text, undecodable bytes replaced, line ends as Python's text mode reads
    them; None when absent or not a regular file (a FIFO is never opened)."""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return _text(data)


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


def _repos(root: Path, config: HubConfig, *, network: bool) -> tuple[RepoState, ...]:
    checkouts = [
        # The hub line is the hub repo's own branch, not a repo's.
        _Checkout(HUB_LINE_NAME, root, config.project.hub_repo, config.project.default_branch),
        *(
            _Checkout(
                repo.dir, root.parent / repo.dir, repo.github, config.default_branch_for(repo.dir)
            )
            for repo in config.repos
        ),
    ]
    git = shutil.which("git")
    gh = shutil.which("gh") if network else None
    deadline = time.monotonic() + BRIEF_DEADLINE
    states = [RepoState(name=checkout.name, checkout=False) for checkout in checkouts]
    indexes = [index for index, checkout in enumerate(checkouts) if _is_checkout(checkout.path)]
    shown = [checkouts[index] for index in indexes]
    with (
        ThreadPoolExecutor(max_workers=MAX_WORKERS) as git_pool,
        ThreadPoolExecutor(max_workers=MAX_WORKERS) as gh_pool,
    ):
        # Spec Q8: each repo's git branch and gh pr list start at once; status, rev-list and
        # gh run list start as soon as that repo's own branch is known.
        branches = {
            git_pool.submit(_branch, git, checkout.path, deadline): position
            for position, checkout in enumerate(shown)
        }
        prs = [
            gh_pool.submit(_gh_output, gh, root, _pr_arguments(checkout), deadline=deadline)
            for checkout in shown
        ]
        later: dict[int, tuple[Future[str], Future[str], Future[GhAnswer]]] = {}
        for branch in as_completed(branches):
            checkout = shown[branches[branch]]
            later[branches[branch]] = (
                git_pool.submit(_git_output, git, checkout.path, _STATUS, deadline=deadline),
                git_pool.submit(
                    _git_output,
                    git,
                    checkout.path,
                    ("rev-list", "--count", f"HEAD..origin/{checkout.branch}"),
                    deadline=deadline,
                ),
                gh_pool.submit(_gh_output, gh, root, _run_arguments(checkout), deadline=deadline),
            )
        for (branch, position), pr in zip(branches.items(), prs, strict=True):
            checkout = shown[position]
            status, behind, run = later[position]
            states[indexes[position]] = RepoState(
                name=checkout.name,
                checkout=True,
                branch=branch.result(),
                dirty=len([line for line in status.result().splitlines() if line]),
                behind=behind.result(),
                base=f"origin/{checkout.branch}",
                default_branch=checkout.branch,
                prs=pr.result().text,
                ci=run.result().text,
                ci_timed_out=run.result().timed_out,
            )
    return tuple(states)


def _pr_arguments(checkout: _Checkout) -> tuple[str, ...]:
    return ("pr", "list", "-R", checkout.github, "--author", "@me", "--json", "number,title") + (
        "-q",
        _PR_QUERY,
    )


def _run_arguments(checkout: _Checkout) -> tuple[str, ...]:
    return ("run", "list", "-R", checkout.github, "--branch", checkout.branch, "-L", "3") + (
        "--json",
        "name,conclusion",
        "-q",
        _FAILED_RUNS_QUERY,
    )


def _branch(git: str | None, folder: Path, deadline: float) -> str:
    def output(*arguments: str) -> str:
        return _git_output(git, folder, arguments, deadline=deadline)

    return (
        output("branch", "--show-current") or f"detached@{output('rev-parse', '--short', 'HEAD')}"
    )


def _is_checkout(path: Path) -> bool:
    try:
        mode = os.lstat(path / ".git").st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) or stat.S_ISREG(mode)


def _git_output(git: str | None, folder: Path, arguments: Sequence[str], *, deadline: float) -> str:
    # Like the old script: git's stdout whatever its exit code; nothing when it cannot answer.
    timeout = _time_left(deadline)
    if git is None or timeout is None:
        return ""
    try:
        result = run_child(
            [git, *arguments],
            cwd=folder,
            env=git_env(os.environ, optional_locks=False),
            timeout=timeout,
            own_session=False,
        )
    except OSError, ChildTimedOutError:
        return ""
    return _text(result.stdout).strip()


def _time_left(deadline: float) -> float | None:
    """The timeout of a call started now: what is left before ``deadline``, None when nothing."""
    left = deadline - time.monotonic()
    return left if left > 0 else None


def _gh_output(
    gh: str | None, root: Path, arguments: Sequence[str], *, deadline: float
) -> GhAnswer:
    """``gh``'s output, empty when there is no ``gh`` (no network) or it fails; ``timed_out``
    when the deadline ended it (run_child kills the child) or left it no time to start."""
    if gh is None:
        return GhAnswer("", timed_out=False)
    timeout = _time_left(deadline)
    if timeout is None:
        return GhAnswer("", timed_out=True)
    try:
        # The environment as it is: -R names the repo, so gh does not look for one from the
        # cwd and git's location variables cannot mislead it.
        result = run_child(
            [gh, *arguments],
            cwd=root,
            env=dict(os.environ),
            timeout=timeout,
            own_session=False,
        )
    except ChildTimedOutError:
        return GhAnswer("", timed_out=True)
    except OSError:
        return GhAnswer("", timed_out=False)
    return GhAnswer(_CONTROLS.sub("", _text(result.stdout)).strip(), timed_out=False)
