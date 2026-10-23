# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Make the hub worktree the release run commits the pin in, and print its target, as JSON.

``hub_branch.py --issue <team>-<n> --slug <slug> --config <json>`` runs in the hub (the node's
default cwd), after the owner's approval. ``--config`` is what ``hub step config --branch <issue>
--slug <slug>`` printed (this script opens no ``hub.json``): the branch ``<branch_prefix><issue
lower>-<slug>`` and its name, resolved by the CLI as ``hub run`` resolves the prefix
(``hub.local.json`` first), and the hub's target skeleton (its GitHub name, default branch and
conventions). It adds a git worktree of the hub at ``.claude/worktrees/<name>`` (ignored by the
hub) on that branch, based on the local ``origin/<default_branch>`` (no fetch: a script gets no
tokens). The default branch is never checked out or committed to. A resumed run finds its
worktree and reuses it. The hub is not a repo of ``hub.json``, so ``hub step worktree`` cannot
make this branch.

Prints ``{"path", "branch", "base", "target"}``; ``target`` is the skeleton with the path,
branch, base and gate, what ``hub step commits|pr --target`` read (titles not configured: the PR
title is the commit subject). A config that is not usable (not JSON, no hub target, no branch, a
``claude/`` branch, a name other than the issue's and slug's), a bad issue or slug, or a branch
equal to the default branch exits 2; a git failure exits 1. Both say why on stderr.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

PROG = "hub_branch.py"
MAX_CONFIG_BYTES = 1024 * 1024
ISSUE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,15}-[0-9]{1,9}$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORKTREES = ".claude/worktrees"
GIT_TIMEOUT = 120


class RefusedError(Exception):
    """Bad input: exit 2."""


class GitFailedError(Exception):
    """A git command failed: exit 1."""


class HubConfig(NamedTuple):
    target: dict[str, object]
    default_branch: str
    name: str
    branch: str


def _text(value: object, key: str) -> str:
    found = value.get(key) if isinstance(value, dict) else None
    return found if isinstance(found, str) else ""


def read_config(text: str, *, issue: str, slug: str) -> HubConfig:
    """The run's branch and the hub's target skeleton, from ``hub step config``'s output."""
    if len(text.encode()) > MAX_CONFIG_BYTES:
        raise RefusedError("the config: larger than 1 MiB")
    try:
        value = json.loads(text)
    except ValueError as error:
        raise RefusedError(f"the config: {error}") from None
    hub = value.get("hub") if isinstance(value, dict) else None
    target = hub.get("target") if isinstance(hub, dict) else None
    if not isinstance(target, dict) or not HUB_REPO.fullmatch(_text(target, "github")):
        raise RefusedError("the config: hub.target has no <owner>/<name> github")
    default = _text(target, "default_branch")
    if not default:
        raise RefusedError("the config: hub.target.default_branch is missing")
    name, branch = _text(value, "branch_name"), _text(value, "branch")
    if name != f"{issue.lower()}-{slug}":
        raise RefusedError("the config: branch_name is not <issue lower>-<slug>")
    if not branch or branch.startswith("claude/"):
        raise RefusedError("the config: branch is missing (or names claude/)")
    return HubConfig(target=target, default_branch=default, name=name, branch=branch)


def target_for(*, hub: Path, issue: str, config: HubConfig, base: str) -> dict[str, object]:
    """The worktree and the ``--target`` that ``hub step commits|pr`` read."""
    path = str(hub / WORKTREES / config.name)
    gate = f"hub workflow release, {issue}: the hub change approved at its gate"
    facts = {"path": path, "branch": config.branch, "base": base, "gate": gate}
    target = {**config.target, **facts}
    return {"path": path, "branch": config.branch, "base": base, "target": target}


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


def branch_for(root: Path, *, issue: str, slug: str, text: str) -> dict[str, object]:
    """The run's worktree, made or found, and its target; ``RefusedError`` or ``GitFailedError``."""
    if not ISSUE.fullmatch(issue):
        raise RefusedError("--issue must be <team>-<n>")
    if not SLUG.fullmatch(slug):
        raise RefusedError("--slug must be lowercase words joined by hyphens")
    config = read_config(text, issue=issue, slug=slug)
    planned = target_for(hub=root, issue=issue, config=config, base="")
    if planned["branch"] == config.default_branch:
        raise RefusedError(f"the branch {planned['branch']} is the default branch")
    base = _worktree(root, planned, default_branch=config.default_branch)
    return target_for(hub=root, issue=issue, config=config, base=base)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--config", required=True, help="What hub step config printed.")
    given = parser.parse_args(argv)
    try:
        found = branch_for(
            Path.cwd().resolve(), issue=given.issue, slug=given.slug, text=given.config
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
