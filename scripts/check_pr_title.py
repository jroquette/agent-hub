"""PR title lint (ADR 0007): the squash commit subject is ``type(scope): subject``.

Stdlib only, so CI can run it without syncing the workspace:
``python scripts/check_pr_title.py "<title>"``. The same types and scopes are listed in
docs/CONTRIBUTING.md.
"""

import re
import sys
from collections.abc import Sequence

TYPES = ("feat", "fix", "docs", "chore", "refactor", "test", "ci", "build", "perf", "revert")
SCOPES = ("core", "storage", "collector", "cli", "api", "web", "repo", "deps", "ci", "docs")
MAX_LENGTH = 72
TITLE = re.compile(rf"^({'|'.join(TYPES)})\(({'|'.join(SCOPES)})\)!?: \S.*$")


def problems(title: str) -> list[str]:
    """Every reason ``title`` is not a valid PR title; empty when it is valid."""
    found: list[str] = []
    if not TITLE.match(title):
        found.append("must be type(scope): subject, with a known type and scope")
    if len(title) > MAX_LENGTH:
        found.append(f"is {len(title)} characters; at most {MAX_LENGTH}")
    if title.endswith("."):
        found.append("ends with a period")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Print the problems with the title in ``argv`` and return 1 if there are any."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print('usage: check_pr_title.py "<title>"', file=sys.stderr)
        return 2
    found = problems(args[0])
    if not found:
        return 0
    print(f"PR title {args[0]!r}:")
    for problem in found:
        print(f"  - {problem}")
    print(f"types: {', '.join(TYPES)}")
    print(f"scopes: {', '.join(SCOPES)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
