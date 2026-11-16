# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Say how a brain-care run ended, as JSON: the workflow's outcome, even when no PR opened.

``outcome.py inbox [--count N] [--groups N] [--acted N] [--changes N] [--pr URL]`` and
``outcome.py context [--decision trim|skip] [--commits N] [--dirty true|false] [--pr URL]``,
each with ``[--worktree PATH] [--branch NAME]``, read what the earlier steps printed (a step that
did not run reads as blank) and print ``{"outcome", "reason"}``:

- ``inbox``: ``empty`` (no note to review), ``nothing_decided`` (no group reached a gate),
  ``kept`` (the owner kept every group), ``pr_opened`` or ``no_pr`` (the owner approved changes
  but every one was skipped: the PR body would have been empty);
- ``context``: ``declined`` (the owner skipped), ``pr_opened`` or ``no_pr`` (the trim made no
  commit, or left uncommitted changes).

When the run made a hub worktree, the reason says how to remove it: after the merge, or at once
when no PR opened. A count that is not a number exits 2.
"""

import argparse
import json
import sys

PROG = "outcome.py"


class BadInputError(Exception):
    """A count that is not a number: exit 2."""


def _count(text: str, name: str) -> int:
    try:
        return int(text) if text.strip() else 0
    except ValueError:
        raise BadInputError(f"--{name} is not a count") from None


def _cleanup(given: argparse.Namespace) -> str:
    if not given.worktree:
        return ""
    return f"git worktree remove {given.worktree} && git branch -D {given.branch}"


def inbox(given: argparse.Namespace) -> tuple[str, str]:
    count, groups = _count(given.count, "count"), _count(given.groups, "groups")
    acted, changes = _count(given.acted, "acted"), _count(given.changes, "changes")
    cleanup = _cleanup(given)
    if given.pr:
        return "pr_opened", f"opened {given.pr}; after the merge, run: {cleanup}"
    if count == 0:
        return "empty", "the inbox holds no note to review"
    if groups == 0:
        return "nothing_decided", "no group reached a gate: the notes stay in the inbox"
    if acted == 0:
        return "kept", "the owner kept every group in the inbox"
    why = "every approved change was skipped" if changes == 0 else "no PR was opened"
    return "no_pr", f"{why} (see the apply step's skipped list); remove the worktree: {cleanup}"


def context(given: argparse.Namespace) -> tuple[str, str]:
    commits = _count(given.commits, "commits")
    cleanup = _cleanup(given)
    if given.pr:
        return "pr_opened", f"opened {given.pr}; after the merge, run: {cleanup}"
    if given.decision != "trim":
        return "declined", "the owner skipped this month's trim"
    if commits == 0:
        why = "the trim made no commit"
    elif given.dirty == "true":
        why = "the trim left uncommitted changes beside its commit"
    else:
        why = "no PR was opened"
    return "no_pr", f"{why}; remove the worktree: {cleanup}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("workflow", choices=["inbox", "context"])
    for name in ("count", "groups", "acted", "changes", "pr", "decision", "commits", "dirty"):
        parser.add_argument(f"--{name}", default="")
    parser.add_argument("--worktree", default="")
    parser.add_argument("--branch", default="")
    return parser


def main(argv: list[str]) -> int:
    given = _parser().parse_args(argv)
    try:
        found, reason = inbox(given) if given.workflow == "inbox" else context(given)
    except BadInputError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"outcome": found, "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
