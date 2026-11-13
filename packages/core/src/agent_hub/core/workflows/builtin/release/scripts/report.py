# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The run's outcome, from what its steps printed, as JSON (no tracker write).

Each value is a step's output as the run renders it, empty when that step was skipped. There are
two call forms, one for each workflow of the pack; an outcome is the first that applies.

``report.py --count <n> --passed <true|false> --log <path> --go <decision> --pr <url>
--tagged <choice> --pin-go <decision> --pin-pr <url> --version X.Y.Z`` is the ``release``
workflow's form, with all nine options required: ``nothing`` (no PR since the tag), ``blocked``
(the check on the release commit is red: the log's path), ``declined`` (the owner rejected the
release PR), ``stopped`` (the owner stopped at the tag question), ``unpinned`` (the owner
rejected the hub pin), ``released`` (the pin PR is open). A count that is not a number exits 2.

``report.py --verify <true|false> --pin-pr <url> --version X.Y.Z`` is the ``release-pin``
workflow's form. ``--verify``, with any value (an empty one too), selects it: the other options
of the first form are then neither required nor read. ``untagged`` (the tag check did not
answer ``true``), ``unpinned`` (no pin PR was opened), ``released`` (the pin PR is open).

Both forms print ``{"outcome", "version", "pr", "pin_pr", "reason"}``; ``pr`` is empty in the
second one. A missing required option exits 2.
"""

import argparse
import json
import sys

PROG = "report.py"
RELEASE = ("count", "passed", "log", "go", "pr", "tagged", "pin-go", "pin-pr", "version")
VERIFY = ("verify", "pin-pr", "version")
OPTIONS = (*RELEASE, "verify")


def outcome(given: dict[str, str]) -> tuple[str, str]:
    """The outcome and its reason, for the ``release`` workflow's form."""
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


def pin_outcome(given: dict[str, str]) -> tuple[str, str]:
    """The outcome and its reason, for the ``release-pin`` workflow's form (it has no approval)."""
    version = f"v{given['version']}"
    if given["verify"] != "true":
        return "untagged", f"the tag check for {version} did not pass; no hub pin PR was opened"
    if not given["pin-pr"]:
        return "unpinned", f"{version} is tagged; no hub pin PR was opened"
    return "released", f"{version} is tagged; the hub pin PR is open: {given['pin-pr']}"


def joined(argv: list[str], options: frozenset[str]) -> list[str]:
    """``argv`` with each of ``options`` joined to its value (``--name=value``), so a value may
    start with ``-``: the owner's text and the steps' outputs are data, never options."""
    out: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] in options and index + 1 < len(argv):
            out.append(f"{argv[index]}={argv[index + 1]}")
            index += 2
        else:
            out.append(argv[index])
            index += 1
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    for name in OPTIONS:
        parser.add_argument(f"--{name}")
    values = vars(parser.parse_args(joined(argv, frozenset(f"--{name}" for name in OPTIONS))))
    # Which options are required depends on the form, so this check stands in for the parser's:
    # --verify, with any value, selects the release-pin form, and only that form's options are read.
    form = RELEASE if values["verify"] is None else VERIFY
    missing = [f"--{name}" for name in form if values[name.replace("-", "_")] is None]
    if missing:
        parser.error(f"the following arguments are required: {', '.join(missing)}")
    given = {name: str(values[name.replace("-", "_")]).strip() for name in form}
    if form is RELEASE and (not given["count"].isascii() or not given["count"].isdecimal()):
        print(f"{PROG}: --count is not a number: {given['count']!r}", file=sys.stderr)
        return 2
    found, reason = outcome(given) if form is RELEASE else pin_outcome(given)
    result = {
        "outcome": found,
        "version": given["version"],
        "pr": given["pr"] if form is RELEASE and found not in {"nothing", "blocked"} else "",
        "pin_pr": given["pin-pr"] if found == "released" else "",
        "reason": reason,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
