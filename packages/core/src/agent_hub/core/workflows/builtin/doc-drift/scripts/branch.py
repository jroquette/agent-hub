# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Make the repo worktree a doc-drift run commits in, and print its target, as JSON.

``branch.py --repo <dir> --base <sha>`` runs in the hub (the node's default cwd), after the
owner's approval. It reads ``hub.json`` → ``repos[]`` (the entry whose ``dir`` is ``<dir>``: its
``github`` and its default branch, else the project's, else ``main``) and the branch prefix
(``hub.local.json`` → ``project.branch_prefix`` first, as ``hub run`` reads the developer's
prefix, then ``hub.json``'s), and the run's id from ``AGENT_HUB_RUN_ID``. It adds a git worktree
of the repo at ``<repo>/.claude/worktrees/doc-drift-<run id>`` (ignored there, as ``hub
worktree`` uses it) on the new branch ``<prefix>doc-drift-<run id>``, at ``<base>``: the commit
the judge read, so the line numbers it approved are the ones the branch holds. No fetch (a
script gets no token). The repo's own checkout is never changed. A resumed run finds its
worktree and reuses it.

Prints ``{"path", "branch", "base", "target"}``; ``target`` is what ``hub step commits|pr
--target`` read (titles not configured: the PR title is the commit subject). A config that is
not readable, a repo not in ``hub.json``, a missing or ``claude/`` prefix, no run id, a branch
equal to the default branch or an unknown base exits 2; a git failure exits 1. Both say why on
stderr.
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
WORKTREES = ".claude/worktrees"
GIT_TIMEOUT = 120


class RefusedError(Exception):
    """Bad input: exit 2."""


class GitFailedError(Exception):
    """A git command failed: exit 1."""


class RepoConfig(NamedTuple):
    github: str
    default_branch: str
    prefix: str


def _document(path: Path) -> dict[str, object]:
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise RefusedError(f"{path.name}: larger than 1 MiB")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RefusedError(f"{path.name}: {error}") from None
    if not isinstance(value, dict):
        raise RefusedError(f"{path.name}: not a JSON object")
    return value


def _text(value: object, key: str) -> str:
    found = value.get(key) if isinstance(value, dict) else None
    return found if isinstance(found, str) else ""


def read_config(root: Path, repo: str) -> RepoConfig:
    """The repo's facts; the developer's local prefix wins over the hub's."""
    document = _document(root / "hub.json")
    repos = document.get("repos")
    entries = [e for e in repos if isinstance(e, dict)] if isinstance(repos, list) else []
    entry = next((e for e in entries if e.get("dir") == repo), None)
    if entry is None or not REPO_DIR.match(repo):
        raise RefusedError(f"hub.json: no repo {repo} in repos")
    project = document.get("project")
    local = root / "hub.local.json"
    prefix = _text(_document(local).get("project"), "branch_prefix") if local.is_file() else ""
    prefix = prefix or _text(project, "branch_prefix")
    branch = _text(entry, "default_branch") or _text(project, "default_branch") or "main"
    github = _text(entry, "github")
    if not GITHUB.fullmatch(github):
        raise RefusedError(f"hub.json: repos[{repo}].github is not <owner>/<name>")
    if not prefix or prefix.startswith("claude/"):
        raise RefusedError("hub.json: project.branch_prefix is missing (or names claude/)")
    return RepoConfig(github=github, default_branch=branch, prefix=prefix)


def target_for(
    *, repo: Path, run_id: str, prefix: str, default_branch: str, github: str, base: str
) -> dict[str, object]:
    """The worktree and the ``--target`` that ``hub step commits|pr`` read."""
    name = f"doc-drift-{run_id}"
    path, branch = str(repo / WORKTREES / name), f"{prefix}{name}"
    target = {
        "path": path,
        "branch": branch,
        "base": base,
        "default_branch": default_branch,
        "github": github,
        "gate": (
            f"doc-drift run {run_id}: docs-only diff check passed; every line approved at the gate"
        ),
        "conventions": {
            "branch": "",
            "commit_title": "",
            "pr_title": "",
            "titles_configured": False,
            "pr_title_explicit": False,
        },
    }
    return {"path": path, "branch": branch, "base": base, "target": target}


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


def branch_for(root: Path, *, repo: str, base: str) -> dict[str, object]:
    """The run's worktree, made or found, and its target; ``RefusedError`` or ``GitFailedError``."""
    config = read_config(root, repo)
    run_id = os.environ.get("AGENT_HUB_RUN_ID", "")
    if not RUN_ID.fullmatch(run_id):
        raise RefusedError("AGENT_HUB_RUN_ID is not a run id")
    if not SHA.fullmatch(base):
        raise RefusedError(f"--base {base} is not a commit id")
    checkout = (root.parent / repo).resolve()

    def target(commit: str) -> dict[str, object]:
        return target_for(
            repo=checkout,
            run_id=run_id,
            prefix=config.prefix,
            default_branch=config.default_branch,
            github=config.github,
            base=commit,
        )

    planned = target("")
    if planned["branch"] == config.default_branch:
        raise RefusedError(f"the branch {planned['branch']} is the default branch")
    if not (checkout / ".git").exists():
        raise RefusedError(f"{repo} is not cloned at {checkout}")
    return target(_worktree(checkout, planned, base))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    given = parser.parse_args(argv)
    try:
        found = branch_for(Path.cwd().resolve(), repo=given.repo, base=given.base)
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
