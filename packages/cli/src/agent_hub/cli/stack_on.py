"""``hub worktree --stack-on <PR url>``: the hub repo and branch a stacked task starts from.

A task stacked on a blocker still in review starts from the blocker's pull request branch, in
the repo of that pull request: the repo is the ``hub.json`` repo whose ``github`` is the URL's
``<owner>/<repo>``, and the branch is the pull request's head, read with ``gh pr view``. Only an
open pull request is stacked on; a merged one is in the default branch already.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import WorktreeError, WorktreeUsageError
from agent_hub.cli.init_report import shown_path
from agent_hub.cli.worktree_steps import ChildRunner
from agent_hub.core.hub_config.model import HubConfig

_PR_URL: Final = re.compile(
    r"https://github\.com/(?P<github>[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100})"
    r"/pull/[1-9][0-9]{0,8}/?"
)
# gh answers in seconds; a hung call must not hold the worktree's creation.
_GH_TIMEOUT: Final = 60.0


@dataclass(frozen=True, kw_only=True, slots=True)
class StackBase:
    """Where a stacked task starts: ``repo`` (its ``hub.json`` dir) from ``origin/<branch>``."""

    repo: str
    branch: str


def stack_repo(config: HubConfig, url: str) -> str:
    """The ``hub.json`` repo dir of the pull request ``url``; ``WorktreeUsageError`` when the
    URL is not a GitHub pull request URL or names a repo the hub does not have."""
    found = _PR_URL.fullmatch(url)
    if found is None:
        msg = (
            f"--stack-on takes a pull request URL, https://github.com/<owner>/<repo>/pull/<n>;"
            f" got {shown_path(url)}"
        )
        raise WorktreeUsageError(msg)
    github = found["github"].casefold()
    for repo in config.repos:
        if repo.github.casefold() == github:
            return repo.dir
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
    request, or it is not open.
    """
    repo = stack_repo(config, url)
    viewed = runner(
        [gh, "pr", "view", url, "--json", "headRefName,state"],
        cwd=cwd,
        env=env,
        timeout=_GH_TIMEOUT,
        own_session=False,
    )
    head, state = _head_and_state(viewed)
    if head is None:
        msg = f"could not read {url} with gh: {_first_line(viewed)}; run gh auth status"
        raise WorktreeError(msg)
    if state != "OPEN":
        msg = (
            f"{url} is {state.lower()}, not open: start from the default branch"
            " (drop --stack-on)"
        )
        raise WorktreeError(msg)
    return StackBase(repo=repo, branch=head)


def _head_and_state(viewed: ChildResult) -> tuple[str | None, str]:
    if viewed.returncode != 0:
        return None, ""
    try:
        found = json.loads(viewed.stdout)
    except ValueError:
        return None, ""
    if not isinstance(found, dict):
        return None, ""
    head = found.get("headRefName")
    state = found.get("state")
    if not isinstance(head, str) or not head or not isinstance(state, str):
        return None, ""
    return head, state


def _first_line(result: ChildResult) -> str:
    text = (result.stderr or result.stdout).decode(errors="replace").strip()
    line = text.splitlines()[0] if text else f"exit {result.returncode}"
    return shown_path(line)
