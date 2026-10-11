"""``hub setup``'s repos: clone each missing repo next to the hub, fetch each present one.

Every git call setup makes on its own runs with ``setup_git_env``: no call may stop on a
credential prompt (``GIT_TERMINAL_PROMPT=0``), the tracker key never reaches git, and a location
variable the caller set (``GIT_DIR``) never points git at another repo than the one the call
names. Per ``repos`` entry, in ``hub.json`` order, at ``<hub parent>/<dir>``: no entry is
cloned, over the scheme of the hub's own origin (``git_defaults.read_remote_scheme``); a folder
(or a link to one) holding a ``.git`` entry is fetched once ``rev-parse --verify -q HEAD`` finds
a commit there; anything else is reported and never touched. Only git's exit code is read: its
output, which can name a URL or a credential, is discarded, and no URL is printed. Each clone
or fetch runs at most ``NETWORK_TIMEOUT_SECONDS`` (spec D-repos, D-url).

The commit check (errata E27, E28): exit 1 is a repo with no commit, what a clone killed at its
timeout or by Ctrl-C leaves, where a fetch would succeed and hide it; any other failing exit is
a ``.git`` git cannot read, so not a repository; a check that times out (``GIT_TIMEOUT_SECONDS``,
a local read) is reported as the fetch timing out after that limit, as the fetch never ran.
Every call aimed at ``../<dir>`` sets ``GIT_CEILING_DIRECTORIES`` to the workspace, so git never
searches above ``../<dir>`` and runs in a repo that holds the workspace. Setup deletes nothing.
"""

import os
import shutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final, NamedTuple

from agent_hub.cli.child_process import run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.git_defaults import GIT_TIMEOUT_SECONDS, RemoteScheme, read_remote_scheme
from agent_hub.cli.run_children import child_env
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.workspace_repos import WorkspaceRepo, workspace_repos
from agent_hub.core.workspace.setup_checklist import ChecklistItem, RepoOutcome, repo_item

# A clone of a big repo over a slow link takes minutes; a call that hangs is cut here.
NETWORK_TIMEOUT_SECONDS: Final = 600.0
# Git's output is never shown: only this much of each stream is kept, then dropped.
OUTPUT_LIMIT: Final = 65_536

_NO_PROMPT: Final = {"GIT_TERMINAL_PROMPT": "0"}
_GIT_ENTRY: Final = ".git"
_CEILING_VARIABLE: Final = "GIT_CEILING_DIRECTORIES"
# ``rev-parse --verify -q`` exits 1 when the name does not resolve: an unborn HEAD here.
_NO_COMMIT_EXIT: Final = 1


class _Step(NamedTuple):
    """One git call for a repo and the outcomes it can give."""

    argv: list[str]
    done: RepoOutcome
    failed: RepoOutcome
    timed_out: RepoOutcome


def setup_git_env(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` for setup's own git: no tracker key, no location variable, no prompt."""
    return {**child_env(environ), **_NO_PROMPT}


def repo_items(
    config: HubConfig, *, root: Path, home: Path, environ: Mapping[str, str]
) -> Iterator[ChecklistItem]:
    """One ``repo <dir>`` item per ``repos`` entry, each after its clone or fetch ran.

    Without git on the environment's ``PATH``, every repo is ``git not found`` and nothing runs.
    """
    env = setup_git_env(environ)
    repos = workspace_repos(config)
    found = shutil.which("git", path=env.get("PATH", os.defpath))
    if found is None:
        for repo in repos:
            yield repo_item(repo, RepoOutcome.GIT_NOT_FOUND)
        return
    git = os.path.abspath(found)
    scheme = read_remote_scheme(home, env=env)
    parent = root.parent
    for repo in repos:
        yield _repo_item(repo, git=git, parent=parent, scheme=scheme, env=env)


def _repo_item(
    repo: WorkspaceRepo, *, git: str, parent: Path, scheme: RemoteScheme, env: Mapping[str, str]
) -> ChecklistItem:
    dest = parent / repo.dir
    if not os.path.lexists(dest):
        # Something may appear at ``dest`` before git starts: git refuses to clone into a
        # non-empty folder (clone failed), and an empty one it may fill holds nothing to lose.
        step = _Step(
            [git, "clone", "--quiet", _clone_url(repo.github, scheme), str(dest)],
            done=RepoOutcome.CLONED,
            failed=RepoOutcome.CLONE_FAILED,
            timed_out=RepoOutcome.CLONE_TIMED_OUT,
        )
        return _run(repo, step, parent=parent, scheme=scheme, env=env)
    # ``isdir`` follows a link: a link to a clone is fetched there (erratum E25).
    if not (os.path.isdir(dest) and os.path.lexists(dest / _GIT_ENTRY)):
        return repo_item(repo, RepoOutcome.NOT_A_REPO)
    bounded = {**env, _CEILING_VARIABLE: str(parent)}
    gap = _commit_gap(repo, git=git, dest=dest, env=bounded)
    if gap is not None:
        return gap
    step = _Step(
        [git, "-C", str(dest), "fetch", "--quiet", "origin"],
        done=RepoOutcome.FETCHED,
        failed=RepoOutcome.FETCH_FAILED,
        timed_out=RepoOutcome.FETCH_TIMED_OUT,
    )
    return _run(repo, step, parent=parent, scheme=scheme, env=bounded)


def _commit_gap(
    repo: WorkspaceRepo, *, git: str, dest: Path, env: Mapping[str, str]
) -> ChecklistItem | None:
    """Why the present repo at ``dest`` is not fetched (no commit, no readable repo), or None."""
    argv = [git, "-C", str(dest), "rev-parse", "--verify", "-q", "HEAD"]
    try:
        result = run_child(
            argv, cwd=dest.parent, env=env, timeout=GIT_TIMEOUT_SECONDS, output_limit=OUTPUT_LIMIT
        )
    except ChildTimedOutError:
        return repo_item(repo, RepoOutcome.FETCH_TIMED_OUT, timeout_seconds=GIT_TIMEOUT_SECONDS)
    except OSError:
        return repo_item(repo, RepoOutcome.GIT_CANNOT_RUN)
    if result.returncode == 0:
        return None
    if result.returncode == _NO_COMMIT_EXIT:
        return repo_item(repo, RepoOutcome.NO_COMMIT)
    return repo_item(repo, RepoOutcome.NOT_A_REPO)


def _run(
    repo: WorkspaceRepo,
    step: _Step,
    *,
    parent: Path,
    scheme: RemoteScheme,
    env: Mapping[str, str],
) -> ChecklistItem:
    # Read at call time, so a test can shorten it.
    timeout = NETWORK_TIMEOUT_SECONDS
    try:
        result = run_child(
            step.argv, cwd=parent, env=env, timeout=timeout, output_limit=OUTPUT_LIMIT
        )
    except ChildTimedOutError:
        # The error's text names git's path: the line is built from the constant alone.
        return repo_item(repo, step.timed_out, timeout_seconds=timeout)
    except OSError:
        # Found on PATH but it cannot start (erratum E24).
        return repo_item(repo, RepoOutcome.GIT_CANNOT_RUN)
    if result.returncode != 0:
        return repo_item(repo, step.failed, returncode=result.returncode)
    return repo_item(repo, step.done, scheme=scheme)


def _clone_url(github: str, scheme: RemoteScheme) -> str:
    if scheme == "ssh":
        return f"git@github.com:{github}.git"
    return f"https://github.com/{github}.git"
