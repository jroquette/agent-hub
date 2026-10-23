# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Make the repo worktree a doc-drift run commits in, and print its target, as JSON.

``branch.py --repo <dir> --base <sha> --config <json>`` runs in the hub (the node's default cwd),
after the owner's approval. ``--config`` is what ``hub step config --branch doc-drift
--run-slug`` printed (this script opens no ``hub.json``): the branch ``<prefix>doc-drift-<run
id>`` and its name, both resolved by the CLI as ``hub run`` resolves the prefix, and the entry of
``repos[]`` whose ``dir`` is ``<dir>`` with its target skeleton (its GitHub name, default branch
and conventions). It adds a git worktree of the repo at ``<repo>/.claude/worktrees/<name>``
(ignored there, as ``hub worktree`` uses it) on that branch, at ``<base>``: the commit the judge
read, so the line numbers it approved are the ones the branch holds. No fetch (a script gets no
token). The repo's own checkout is never changed. A resumed run finds its worktree and reuses
it.

Prints ``{"path", "branch", "base", "target"}``; ``target`` is the skeleton with the path,
branch, base and gate, what ``hub step commits|pr --target`` read (titles not configured: the PR
title is the commit subject). A config that is not usable (not JSON, no such repo, no branch, a
``claude/`` branch), no run id, a branch equal to the default branch or an unknown base exits 2;
a git failure exits 1. Both say why on stderr.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

PROG = "branch.py"
MAX_CONFIG_BYTES = 1024 * 1024
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
GITHUB = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REPO_DIR = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
SHA = re.compile(r"^[0-9a-f]{7,64}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
WORKTREES = ".claude/worktrees"
GIT_TIMEOUT = 120


class RefusedError(Exception):
    """Bad input: exit 2."""


class GitFailedError(Exception):
    """A git command failed: exit 1."""


class RepoConfig(NamedTuple):
    target: dict[str, object]
    default_branch: str
    name: str
    branch: str


def _text(value: object, key: str) -> str:
    found = value.get(key) if isinstance(value, dict) else None
    return found if isinstance(found, str) else ""


def read_config(text: str, repo: str) -> RepoConfig:
    """The run's branch and the repo's target skeleton, from ``hub step config``'s output."""
    if len(text.encode()) > MAX_CONFIG_BYTES:
        raise RefusedError("the config: larger than 1 MiB")
    try:
        document = json.loads(text)
    except ValueError as error:
        raise RefusedError(f"the config: {error}") from None
    repos = document.get("repos") if isinstance(document, dict) else None
    entries = [e for e in repos if isinstance(e, dict)] if isinstance(repos, list) else []
    entry = next((e for e in entries if e.get("dir") == repo), None)
    if entry is None or not REPO_DIR.match(repo):
        raise RefusedError(f"the config: no repo {repo} in repos")
    target = entry.get("target")
    if not isinstance(target, dict) or not GITHUB.fullmatch(_text(target, "github")):
        raise RefusedError(f"the config: repos[{repo}].target has no <owner>/<name> github")
    name, run_branch = _text(document, "branch_name"), _text(document, "branch")
    if not NAME.fullmatch(name):
        raise RefusedError("the config: branch_name is not a worktree name (--branch missing?)")
    if not run_branch or run_branch.startswith("claude/"):
        raise RefusedError("the config: branch is missing (or names claude/)")
    default_branch = _text(target, "default_branch") or "main"
    return RepoConfig(target=target, default_branch=default_branch, name=name, branch=run_branch)


def target_for(*, repo: Path, run_id: str, config: RepoConfig, base: str) -> dict[str, object]:
    """The worktree and the ``--target`` that ``hub step commits|pr`` read."""
    path = str(repo / WORKTREES / config.name)
    gate = f"doc-drift run {run_id}: docs-only diff check passed; every line approved at the gate"
    facts = {"path": path, "branch": config.branch, "base": base, "gate": gate}
    target = {**config.target, **facts}
    return {"path": path, "branch": config.branch, "base": base, "target": target}


def _git(folder: Path, *args: str) -> str:
    command = ["git", "-c", "core.hooksPath=/dev/null", *args]
    try:
        done = subprocess.run(  # noqa: S603 - git from PATH, arguments the script built
            command, cwd=folder, capture_output=True, text=True, check=False, timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitFailedError(f"git {args[0]}: {error}") from None
    if done.returncode != 0:
        raise GitFailedError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def _worktree(repo: Path, found: dict[str, object], base: str) -> str:
    """Add the worktree (or find it, on a resumed run); return the base commit."""
    path, branch = Path(str(found["path"])), str(found["branch"])
    try:
        commit = _git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")
    except GitFailedError:
        raise RefusedError(f"unknown commit {base} in {repo.name}; fetch it first") from None
    if path.is_dir() and _git(path, "branch", "--show-current") == branch:
        return commit
    _git(repo, "worktree", "add", "-b", branch, str(path), commit)
    return commit


def branch_for(root: Path, *, repo: str, base: str, text: str) -> dict[str, object]:
    """The run's worktree, made or found, and its target; ``RefusedError`` or ``GitFailedError``."""
    config = read_config(text, repo)
    run_id = os.environ.get("AGENT_HUB_RUN_ID", "")
    if not RUN_ID.fullmatch(run_id):
        raise RefusedError("AGENT_HUB_RUN_ID is not a run id")
    if not SHA.fullmatch(base):
        raise RefusedError(f"--base {base} is not a commit id")
    checkout = (root.parent / repo).resolve()
    planned = target_for(repo=checkout, run_id=run_id, config=config, base="")
    if planned["branch"] == config.default_branch:
        raise RefusedError(f"the branch {planned['branch']} is the default branch")
    if not (checkout / ".git").exists():
        raise RefusedError(f"{repo} is not cloned at {checkout}")
    commit = _worktree(checkout, planned, base)
    return target_for(repo=checkout, run_id=run_id, config=config, base=commit)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--config", required=True, help="What hub step config printed.")
    given = parser.parse_args(argv)
    try:
        found = branch_for(
            Path.cwd().resolve(), repo=given.repo, base=given.base, text=given.config
        )
    except RefusedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    except GitFailedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
