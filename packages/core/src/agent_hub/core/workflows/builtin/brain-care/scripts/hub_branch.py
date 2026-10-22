# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Make the hub worktree a brain-care run commits in, and print its target, as JSON.

``hub_branch.py --workflow inbox|context`` runs in the hub (the node's default cwd), after the
owner's approvals. It reads ``hub.json`` → ``project`` (``hub_repo``, ``default_branch``,
``branch_prefix``; ``hub.local.json`` → ``project.branch_prefix`` first, as ``hub run`` reads
the developer's prefix) and the run's id from ``AGENT_HUB_RUN_ID``, then adds a git worktree
of the hub at ``.claude/worktrees/brain-care-<workflow>-<run id>`` (ignored by the hub) on the
new branch ``<branch_prefix>brain-care-<workflow>-<run id>``, based on the local
``origin/<default_branch>`` (no fetch: a script gets no tokens). The default branch is never
checked out or committed to. A resumed run finds its worktree and reuses it.

Prints ``{"path", "branch", "base", "target"}``; ``target`` is what ``hub step commits|pr
--target`` read (titles not configured: the PR title is the commit subject). A config that is
not readable, a missing or ``claude/`` prefix, no run id, or a branch equal to the default
branch exits 2; a git failure exits 1. Both say why on stderr.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

PROG = "hub_branch.py"
MAX_CONFIG_BYTES = 1024 * 1024
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
HUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORKTREES = ".claude/worktrees"
GIT_TIMEOUT = 120


class RefusedError(Exception):
    """Bad input: exit 2."""


class GitFailedError(Exception):
    """A git command failed: exit 1."""


class HubConfig(NamedTuple):
    github: str
    default_branch: str
    prefix: str


def _project(path: Path) -> dict[str, object]:
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise RefusedError(f"{path.name}: larger than 1 MiB")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RefusedError(f"{path.name}: {error}") from None
    project = value.get("project", {}) if isinstance(value, dict) else None
    if not isinstance(project, dict):
        raise RefusedError(f"{path.name}: not a JSON object with a project object")
    return project


def _text(project: dict[str, object], key: str) -> str:
    found = project.get(key)
    return found if isinstance(found, str) else ""


def read_config(root: Path) -> HubConfig:
    """The hub's ``project`` facts; the developer's local prefix wins over the hub's."""
    project = _project(root / "hub.json")
    local = root / "hub.local.json"
    prefix = _text(_project(local), "branch_prefix") if local.is_file() else ""
    prefix = prefix or _text(project, "branch_prefix")
    github, default = _text(project, "hub_repo"), _text(project, "default_branch")
    if not HUB_REPO.fullmatch(github):
        raise RefusedError("hub.json: project.hub_repo is not <owner>/<name>")
    if not default:
        raise RefusedError("hub.json: project.default_branch is missing")
    if not prefix or prefix.startswith("claude/"):
        raise RefusedError("hub.json: project.branch_prefix is missing (or names claude/)")
    return HubConfig(github=github, default_branch=default, prefix=prefix)


def target_for(
    *,
    hub: Path,
    workflow: str,
    run_id: str,
    prefix: str,
    default_branch: str,
    github: str,
    base: str,
) -> dict[str, object]:
    """The worktree and the ``--target`` that ``hub step commits|pr`` read."""
    name = f"brain-care-{workflow}-{run_id}"
    path, branch = str(hub / WORKTREES / name), f"{prefix}{name}"
    target = {
        "path": path,
        "branch": branch,
        "base": base,
        "default_branch": default_branch,
        "github": github,
        "gate": f"hub workflow {workflow}, run {run_id}: every change approved at its gate",
        "conventions": {
            "branch": "",
            "commit_title": "",
            "pr_title": "",
            "titles_configured": False,
            "pr_title_explicit": False,
        },
    }
    return {"path": path, "branch": branch, "base": base, "target": target}


def _git(root: Path, *args: str) -> str:
    command = ["git", "-c", "core.hooksPath=/dev/null", *args]
    try:
        done = subprocess.run(  # noqa: S603 - git from PATH, arguments the script built
            command, cwd=root, capture_output=True, text=True, check=False, timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitFailedError(f"git {args[0]}: {error}") from None
    if done.returncode != 0:
        raise GitFailedError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def _worktree(root: Path, found: dict[str, object], *, default_branch: str) -> str:
    """Add the worktree (or find it, on a resumed run); return its base commit."""
    path, branch = Path(str(found["path"])), str(found["branch"])
    origin = f"origin/{default_branch}"
    try:
        base = _git(root, "rev-parse", "--verify", f"{origin}^{{commit}}")
    except GitFailedError:
        raise GitFailedError(f"no {origin} in the hub's clone; fetch it first") from None
    if path.is_dir() and _git(path, "branch", "--show-current") == branch:
        return _git(path, "merge-base", base, "HEAD")
    _git(root, "worktree", "add", "-b", branch, str(path), base)
    return base


def branch_for(root: Path, *, workflow: str) -> dict[str, object]:
    """The run's worktree, made or found, and its target; ``RefusedError`` or ``GitFailedError``."""
    config = read_config(root)
    run_id = os.environ.get("AGENT_HUB_RUN_ID", "")
    if not RUN_ID.fullmatch(run_id):
        raise RefusedError("AGENT_HUB_RUN_ID is not a run id")

    def target(base: str) -> dict[str, object]:
        return target_for(
            hub=root,
            workflow=workflow,
            run_id=run_id,
            prefix=config.prefix,
            default_branch=config.default_branch,
            github=config.github,
            base=base,
        )

    planned = target("")
    if planned["branch"] == config.default_branch:
        raise RefusedError(f"the branch {planned['branch']} is the default branch")
    return target(_worktree(root, planned, default_branch=config.default_branch))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--workflow", required=True, choices=["inbox", "context"])
    given = parser.parse_args(argv)
    try:
        found = branch_for(Path.cwd().resolve(), workflow=given.workflow)
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
