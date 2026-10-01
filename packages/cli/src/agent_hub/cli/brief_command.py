"""``hub brief``: the session brief (``now.md``, the last journal days, each repo's state).

The hub is ``AGENT_HUB_ROOT`` or the cwd, and its repos are ``../<dir>``. Git runs in each
checkout with ``GIT_OPTIONAL_LOCKS=0`` and git's location variables dropped, so the brief writes
nothing; ``gh`` runs in the hub, and the output keeps the order of ``hub.json``. Every call has a
timeout; a failed, slow or missing tool only leaves its value out, as the old script did. The
text itself is ``agent_hub.core.workspace.brief_text``.
"""

import datetime
import glob
import os
import shutil
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Final, NamedTuple

import typer

from agent_hub.cli.child_process import git_env, run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.workspace.brief_text import (
    JOURNAL_MAX_AGE,
    BriefInputs,
    RepoState,
    brief_text,
    now_verified,
    select_journal,
)

COMMAND: Final = "brief"
BRIEF_GIT_TIMEOUT: Final = 6.0
BRIEF_GH_TIMEOUT: Final = 6.0
NOW_PATH: Final = "brain/now.md"
JOURNAL_GLOB: Final = "brain/journal/[0-9]*/[0-9]*/[0-9][0-9].md"
HUB_LINE_NAME: Final = "hub"
_PR_QUERY: Final = '.[] | "#\\(.number) \\(.title)"'
_FAILED_RUNS_QUERY: Final = '.[] | select(.conclusion=="failure") | .name'


class _Checkout(NamedTuple):
    """A repo the brief shows: its line name, folder and GitHub ``owner/name``."""

    name: str
    path: Path
    github: str


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
    config = load_hub_config_or_exit(root / FILE_LABEL)
    day = today()
    now_text = _file_text(root / NOW_PATH)
    inputs = BriefInputs(
        now_text=now_text,
        now_age_days=None if now_text is None else _age_days(now_text, day),
        journal=_journal(root, day),
        repos=_repos(root, config, network=not no_network),
        network=not no_network,
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
        _Checkout(HUB_LINE_NAME, root, config.project.hub_repo),
        *(_Checkout(repo.dir, root.parent / repo.dir, repo.github) for repo in config.repos),
    ]
    base = f"origin/{config.project.default_branch}"
    git = shutil.which("git")
    states = [_git_state(checkout, git=git, base=base) for checkout in checkouts]
    gh = shutil.which("gh") if network else None
    if gh is None:
        return tuple(states)
    shown = [index for index, state in enumerate(states) if state.checkout]
    outputs = _gh_outputs(
        gh,
        root,
        repos=[checkouts[index].github for index in shown],
        branch=config.project.default_branch,
    )
    for index, (prs, ci) in zip(shown, outputs, strict=True):
        states[index] = states[index].model_copy(update={"prs": prs, "ci": ci})
    return tuple(states)


def _git_state(checkout: _Checkout, *, git: str | None, base: str) -> RepoState:
    if not _is_checkout(checkout.path):
        return RepoState(name=checkout.name, checkout=False)

    def output(*arguments: str) -> str:
        return _git_output(git, checkout.path, arguments)

    branch = (
        output("branch", "--show-current") or f"detached@{output('rev-parse', '--short', 'HEAD')}"
    )
    status = output("status", "--porcelain")
    return RepoState(
        name=checkout.name,
        checkout=True,
        branch=branch,
        dirty=len([line for line in status.splitlines() if line]),
        behind=output("rev-list", "--count", f"HEAD..{base}"),
        base=base,
    )


def _is_checkout(path: Path) -> bool:
    try:
        mode = os.lstat(path / ".git").st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode) or stat.S_ISREG(mode)


def _git_output(git: str | None, folder: Path, arguments: Sequence[str]) -> str:
    # Like the old script: git's stdout whatever its exit code; nothing when it cannot answer.
    if git is None:
        return ""
    try:
        result = run_child(
            [git, *arguments],
            cwd=folder,
            env=git_env(os.environ, optional_locks=False),
            timeout=BRIEF_GIT_TIMEOUT,
        )
    except OSError, ChildTimedOutError:
        return ""
    return _text(result.stdout).strip()


def _gh_outputs(gh: str, root: Path, *, repos: Sequence[str], branch: str) -> list[tuple[str, str]]:
    """Each repo's open PRs and failing run names, in ``repos`` order."""
    calls = []
    for repo in repos:
        calls.append(["pr", "list", "-R", repo, "--author", "@me", "--json", "number,title"])
        calls[-1] += ["-q", _PR_QUERY]
        calls.append(["run", "list", "-R", repo, "--branch", branch, "-L", "3"])
        calls[-1] += ["--json", "name,conclusion", "-q", _FAILED_RUNS_QUERY]
    outputs = [_gh_output(gh, root, arguments) for arguments in calls]
    return [(outputs[index], outputs[index + 1]) for index in range(0, len(outputs), 2)]


def _gh_output(gh: str, root: Path, arguments: Sequence[str]) -> str:
    try:
        result = run_child(
            [gh, *arguments], cwd=root, env=dict(os.environ), timeout=BRIEF_GH_TIMEOUT
        )
    except OSError, ChildTimedOutError:
        return ""
    return _text(result.stdout).strip()
