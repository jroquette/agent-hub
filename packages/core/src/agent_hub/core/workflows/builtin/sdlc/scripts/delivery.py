# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The ``implement`` run's delivery: ``hub step report``'s, the ticket eval and the hub files.

``delivery.py --report JSON --feature SLUG [--eval VERDICT]`` runs in the hub's main checkout
and prints the report's object plus ``hub_files``: the paths under ``brain/features/<SLUG>/``
that ``git status`` shows changed or new (the run's records, for the owner's hub PR: the run
never commits, D-1), sorted. A ``NO-SHIP`` eval names itself as the reason no PR was opened.
Text that is not JSON, a bad slug or a git that fails exits 2.
"""

import argparse
import json
import re
import subprocess
import sys

SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
NO_SHIP = "the ticket eval is NO-SHIP: no PR was opened"


def changed(folder: str) -> list[str]:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "status", "--porcelain", "-z", "--untracked-files=all", "--", folder],  # noqa: S607
        capture_output=True,
        check=True,
        timeout=60,
    )
    entries = done.stdout.decode(errors="replace").split("\0")
    files: list[str] = []
    skip = False
    for entry in entries:
        if skip or not entry:
            skip = False
            continue
        # A rename's entry is followed by its old path.
        skip = entry[0] in "RC"
        files.append(entry[3:])
    return sorted(set(files))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="delivery.py")
    parser.add_argument("--report", required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--eval", dest="verdict", default="")
    given = parser.parse_args(argv)
    try:
        report = json.loads(given.report)
    except ValueError:
        report = None
    if not isinstance(report, dict) or SLUG.fullmatch(given.feature) is None:
        print("delivery.py: --report is not a JSON object, or --feature no slug", file=sys.stderr)
        return 2
    try:
        files = changed(f"brain/features/{given.feature}/")
    except (OSError, subprocess.SubprocessError) as error:
        print(f"delivery.py: git status failed: {error}", file=sys.stderr)
        return 2
    if given.verdict == "NO-SHIP" and report.get("delivery") == "failed":
        report |= {"stage": "evaluating", "reason": NO_SHIP}
    print(json.dumps({**report, "hub_files": files}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
