"""``hub worktree --stack-on <PR url>``: the hub repo and branch a stacked task starts from.

A task stacked on a blocker still in review starts from the blocker's pull request branch, in
the repo of that pull request: the repo is the ``hub.json`` repo whose ``github`` is the URL's
``<owner>/<repo>``, and the branch is the pull request's head, read through GitHub's REST API
(``gh api repos/<owner>/<repo>/pulls/<n>``; ``gh pr view`` is GraphQL, which a cloud session's
proxy refuses). Only an open pull request whose branch is in that repo is stacked on: a merged
one is in the default branch already, and a fork's branch is not on the repo's ``origin``.
"""

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import WorktreeError, WorktreeUsageError
from agent_hub.cli.init_report import shown_path
from agent_hub.cli.worktree_steps import ChildRunner, StackBase
from agent_hub.core.hub_config.model import HubConfig, Repo

_PR_URL: Final = re.compile(
    r"https://github\.com/(?P<github>[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100})"
    r"/pull/(?P<number>[1-9][0-9]{0,8})/?"
)
# gh answers in seconds; a hung call must not hold the worktree's creation.
_GH_TIMEOUT: Final = 60.0


def stack_repo(config: HubConfig, url: str) -> str:
    """The ``hub.json`` repo dir of the pull request ``url``.

    ``WorktreeUsageError`` when the URL is not a GitHub pull request URL or names a repo the hub
    does not have.
    """
    return _stacked_pull(config, url)[0].dir


def _stacked_pull(config: HubConfig, url: str) -> tuple[Repo, str]:
    """The ``hub.json`` repo of the pull request ``url`` and the pull request's number."""
    found = _PR_URL.fullmatch(url)
    if found is None:
        msg = (
            "--stack-on takes a pull request URL, https://github.com/<owner>/<repo>/pull/<n>;"
            f" got {shown_path(url)}"
        )
        raise WorktreeUsageError(msg)
    github = found["github"].casefold()
    for repo in config.repos:
        if repo.github.casefold() == github:
            return repo, found["number"]
    known = " ".join(repo.github for repo in config.repos)
    msg = f"--stack-on: {found['github']} is not a repo of hub.json; its repos are: {known}"
    raise WorktreeUsageError(msg)


def stack_base(
    config: HubConfig,
    url: str,
    *,
    gh: str,
    cwd: Path,
    env: Mapping[str, str],
    runner: ChildRunner,
) -> StackBase:
    """The repo and head branch of the open pull request ``url``.

    ``WorktreeUsageError`` as ``stack_repo``; ``WorktreeError`` when ``gh`` cannot read the pull
    request, it is not open, or its branch is on a fork.
    """
    repo, number = _stacked_pull(config, url)
    viewed = runner(
        [gh, "api", "--method", "GET", f"repos/{repo.github}/pulls/{number}"],
        cwd=cwd,
        env=env,
        timeout=_GH_TIMEOUT,
        own_session=False,
    )
    read = _read_pull(viewed)
    if read is None:
        msg = f"could not read {url} with gh: {_first_line(viewed)}; run gh auth status"
        raise WorktreeError(msg)
    head, state, fork = read
    if state != "OPEN":
        msg = f"{url} is {state.lower()}, not open: start from the default branch (drop --stack-on)"
        raise WorktreeError(msg)
    if fork:
        msg = (
            f"{url} comes from a fork: its branch {shown_path(head)} is not on {repo.dir}'s origin"
        )
        raise WorktreeError(msg)
    return StackBase(repo=repo.dir, branch=head)


def _read_pull(viewed: ChildResult) -> tuple[str, str, bool] | None:
    """The head branch, state (``OPEN``, ``CLOSED`` or ``MERGED``) and fork flag of the pull
    request the REST read printed, else None. A head repo other than the base repo, or gone
    (``null``: its fork was deleted), is a fork."""
    if viewed.returncode != 0:
        return None
    try:
        found = json.loads(viewed.stdout)
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    head, state = found.get("head"), found.get("state")
    if not isinstance(head, dict) or not isinstance(state, str):
        return None
    branch, base = head.get("ref"), _repo_name(found.get("base"))
    if not isinstance(branch, str) or not branch or base is None:
        return None
    fork = _repo_name(head) != base
    return branch, "MERGED" if found.get("merged") else state.upper(), fork


def _repo_name(side: object) -> str | None:
    """The ``owner/name`` (case folded) of a pull request side's ``repo``, else None."""
    repo = side.get("repo") if isinstance(side, dict) else None
    name = repo.get("full_name") if isinstance(repo, dict) else None
    return name.casefold() if isinstance(name, str) and name else None


def _first_line(result: ChildResult) -> str:
    text = (result.stderr or result.stdout).decode(errors="replace").strip()
    line = text.splitlines()[0] if text else f"exit {result.returncode}"
    return shown_path(line)
