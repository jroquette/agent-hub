# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The release run's outcome, from what its steps printed, as JSON (no tracker write).

``report.py --count <n> --passed <true|false> --log <path> --go <decision> --pr <url>
--tagged <choice> --pin-go <decision> --pin-pr <url> --version X.Y.Z``: each value is a step's
output as the run renders it, empty when that step was skipped. The first that applies:
``nothing`` (no PR since the tag), ``blocked`` (the check on the release commit is red: the
log's path), ``declined`` (the owner rejected the release PR), ``stopped`` (the owner stopped at
the tag question), ``unpinned`` (the owner rejected the hub pin), ``released`` (the pin PR is
open).

Prints ``{"outcome", "version", "pr", "pin_pr", "reason"}``. A count that is not a number exits 2.
"""

import argparse
import json
import sys

PROG = "report.py"
OPTIONS = ("count", "passed", "log", "go", "pr", "tagged", "pin-go", "pin-pr", "version")


def outcome(given: dict[str, str]) -> tuple[str, str]:
    version = f"v{given['version']}"
    if given["count"] == "0":
        return "nothing", "no PR merged since the last tag: nothing to release"
    if given["passed"] != "true":
        return "blocked", f"the check on the release commit is red; its log: {given['log']}"
    if given["go"] != "approve" or not given["pr"]:
        return "declined", f"the owner did not approve the release PR for {version}"
    if given["tagged"] != "tagged":
        return "stopped", f"stopped before {version} was tagged; the release PR: {given['pr']}"
    if given["pin-go"] != "approve" or not given["pin-pr"]:
        return "unpinned", f"{version} is tagged; the owner did not approve the hub pin"
    return "released", f"{version} is tagged; the hub pin PR is open: {given['pin-pr']}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    for name in OPTIONS:
        parser.add_argument(f"--{name}", required=True)
    values = vars(parser.parse_args(argv))
    given = {name: str(values[name.replace("-", "_")]).strip() for name in OPTIONS}
    if not given["count"].isascii() or not given["count"].isdecimal():
        print(f"{PROG}: --count is not a number: {given['count']!r}", file=sys.stderr)
        return 2
    found, reason = outcome(given)
    result = {
        "outcome": found,
        "version": given["version"],
        "pr": "" if found in {"nothing", "blocked"} else given["pr"],
        "pin_pr": given["pin-pr"] if found == "released" else "",
        "reason": reason,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
