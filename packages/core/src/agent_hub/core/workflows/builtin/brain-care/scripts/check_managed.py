# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Refuse a brain-care ``context`` trim that changes a managed file, as JSON.

``check_managed.py --worktree PATH --base SHA`` runs after the ``trim`` agent, in the run's hub
worktree. It reads which files are managed from ``hub.lock`` as the base commit holds it (the
agent cannot change the answer by editing the lock), and the files the branch changes from the
base, commits and uncommitted edits alike (``git diff --name-only <base>``). A managed file, or
``hub.lock`` itself, changes only through ``hub.json`` or its seeded sibling and ``hub sync``:
any such change exits 1 and names the files, so no PR opens. Otherwise prints ``{"changed",
"managed": []}`` and exits 0. A git failure (an unknown base) exits 1 too.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROG = "check_managed.py"
LOCK = "hub.lock"
GIT_TIMEOUT = 120


class GitFailedError(Exception):
    """A git command failed: exit 1."""


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
    return done.stdout


def managed_paths(lock_text: str) -> set[str]:
    """The paths a ``hub.lock`` text records as managed; none when it is not a lock."""
    try:
        document = json.loads(lock_text)
    except ValueError:
        return set()
    found = document.get("files") if isinstance(document, dict) else None
    if not isinstance(found, dict):
        return set()
    return {
        path
        for path, facts in found.items()
        if isinstance(facts, dict) and facts.get("ownership") == "managed"
    }


def check(root: Path, *, base: str) -> tuple[list[str], list[str]]:
    """The files the branch changes from ``base``, and the managed ones among them."""
    try:
        lock = _git(root, "cat-file", "blob", f"{base}:{LOCK}")
    except GitFailedError:
        lock = ""
    _git(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    changed = sorted(set(_git(root, "diff", "--name-only", base).splitlines()))
    managed = managed_paths(lock) | {LOCK}
    return changed, [path for path in changed if path in managed]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--base", required=True)
    given = parser.parse_args(argv)
    try:
        changed, managed = check(Path(given.worktree), base=given.base)
    except GitFailedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    if managed:
        named = ", ".join(managed)
        print(
            f"{PROG}: the trim changes managed files ({named}); change them through hub.json or"
            f" their seeded sibling and hub sync, never in this PR",
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"changed": changed, "managed": managed}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
