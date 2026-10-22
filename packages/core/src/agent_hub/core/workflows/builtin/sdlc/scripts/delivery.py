# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The ``implement`` run's delivery: ``hub step report``'s, the ticket eval and its hub files.

``delivery.py --report JSON --feature SLUG --brief PATH [--eval VERDICT] [--eval-delivery NAME]
[--request N] [--superseded TEXT]`` runs in the hub's main checkout and prints the report's
object plus ``hub_files``: the files under ``brain/features/<SLUG>/`` that ``git status`` shows changed or
new and that are this run's (D-1: the run never commits them), relative to that folder, sorted.
This run's are the ticket's folder (the brief's), the eval ``NAME``'s ``evals/`` files, the
change requests whose ``run_id`` is this run's (``AGENT_HUB_RUN_ID``) or numbered ``N`` (the
decision a lost run left), with their decisions, and ``plan.md`` (whose changes may include
another run's amendment), and ``superseded``: ``TEXT``, each approval the plan moved past
("change request n approved but superseded by plan vN: not applied", A23), so the owner sees
it. A ``NO-SHIP`` eval names itself as the reason no PR was opened. Text
that is not JSON, a bad slug or a git that fails exits 2.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
REQUEST = re.compile(r"change-requests/([1-9][0-9]{0,5})(?:\.decision)?\.md")
NO_SHIP = "the ticket eval is NO-SHIP: no PR was opened"


def changed(folder: str) -> list[str]:
    """The paths under ``folder`` git shows changed or new, relative to it."""
    argv = ["git", "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all"]
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        [*argv, "--", folder],
        capture_output=True,
        check=True,
        timeout=60,
    )
    entries = done.stdout.decode(errors="replace").split("\0")
    return [entry[3:].removeprefix(folder) for entry in entries if entry]


def ours(
    path: str, *, ticket: str, evals: set[str], requests: set[int], run_id: str, folder: str
) -> bool:
    if path == "plan.md" or path.startswith(f"{ticket}/") or path in evals:
        return True
    found = REQUEST.fullmatch(path)
    if found is None:
        return False
    n = int(found[1])
    if n in requests:
        return True
    try:
        with open(f"{folder}change-requests/{n}.md", encoding="utf-8") as request:
            head = request.read(4096)
    except OSError:
        return False
    return run_id != "" and f"\nrun_id: {run_id}\n" in head


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="delivery.py")
    parser.add_argument("--report", required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--eval", dest="verdict", default="")
    parser.add_argument("--eval-delivery", default="")
    parser.add_argument("--request", default="")
    parser.add_argument("--superseded", default="")
    given = parser.parse_args(argv)
    try:
        report = json.loads(given.report)
    except ValueError:
        report = None
    if not isinstance(report, dict) or SLUG.fullmatch(given.feature) is None:
        print("delivery.py: --report is not a JSON object, or --feature no slug", file=sys.stderr)
        return 2
    folder = f"brain/features/{given.feature}/"
    ticket = str(PurePosixPath(given.brief).parent.relative_to(folder))
    evals = {
        f"evals/{given.eval_delivery}.{kind}" for kind in ("md", "json") if given.eval_delivery
    }
    requests = {int(given.request)} if given.request.isdecimal() else set()
    run_id = os.environ.get("AGENT_HUB_RUN_ID", "")
    try:
        found = changed(folder)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"delivery.py: git status failed: {error}", file=sys.stderr)
        return 2
    files = sorted(
        path
        for path in found
        if ours(path, ticket=ticket, evals=evals, requests=requests, run_id=run_id, folder=folder)
    )
    if given.verdict == "NO-SHIP" and report.get("delivery") == "failed":
        report |= {"stage": "evaluating", "reason": NO_SHIP}
    print(json.dumps({**report, "hub_files": files, "superseded": given.superseded}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
