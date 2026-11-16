# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Write the backlog-care report and the list of approved decisions to apply, as JSON.

``report.py --summary TEXT --unread-line TEXT [--waiting JSON] [--ignored JSON] [--undrafted
JSON] [--skipped-entries JSON] [--descriptions-dropped N]``, the gates' decisions on stdin
(blank when no gate ran). ``--summary`` is ``hygiene.py``'s, ``--unread-line`` ``read.py``'s;
the lists name the issues waiting for a later run, the drafts ignored, the picked issues left
without a draft and the file's entries skipped. A blank argument (a skipped producer) reads as
none.

Prints ``{"outcome", "summary", "apply", "skipped"}``: ``apply`` holds each ``apply`` decision,
and only those, with its draft and label, for ``/triage --backlog`` to write after the run, one
issue at a time (ADR 0030: no node writes the tracker); ``skipped`` the issues to leave as they
are. ``outcome`` is ``apply`` when there is one to apply, else ``report_only``. ``summary`` is
the report's text, ``SUMMARY_CHARS`` at most. Bad stdin or arguments exit 2 with
``report.py: <reason>`` on stderr.
"""

import argparse
import json
import sys

SUMMARY_CHARS = 24_000
CUT = "\n(cut)"
APPLY_KEYS = ("id", "action", "label", "superseded_by", "draft", "note", "approver")


class BadInputError(Exception):
    """Stdin or an argument cannot be read: the run fails at this node."""


def json_list(given: str, name: str) -> list[object]:
    """A JSON array; blank text (a skipped producer) reads as none."""
    if not given.strip():
        return []
    try:
        found = json.loads(given)
    except ValueError as error:
        raise BadInputError(f"{name} is not JSON") from error
    if not isinstance(found, list):
        raise BadInputError(f"{name} is not a list")
    return found


def objects(found: list[object]) -> list[dict[str, object]]:
    return [item for item in found if isinstance(item, dict)]


def decision_line(decision: dict[str, object]) -> str:
    by = f" by {decision.get('approver')}" if decision.get("approver") else ""
    note = f"; note: {decision.get('note')}" if decision.get("note") else ""
    if decision.get("decision") != "apply":
        return f"- {decision.get('id')}: skipped, left as it is{by}{note}"
    if decision.get("action") == "supersede":
        what = f"close as a duplicate of {decision.get('superseded_by')}"
    else:
        what = f"write the draft, label {decision.get('label')}"
    return f"- {decision.get('id')}: apply ({what}){by}{note}"


def ids_line(title: str, found: list[object]) -> list[str]:
    ids = [str(item) for item in found]
    return [f"{title}: {', '.join(ids)}."] if ids else []


def reasons_line(title: str, found: list[dict[str, object]], key: str) -> list[str]:
    shown = [f"{item.get(key)} ({item.get('reason')})" for item in found]
    return [f"{title}: {'; '.join(shown)}."] if shown else []


def summary_of(given: argparse.Namespace, decisions: list[dict[str, object]]) -> str:
    applied = sum(1 for decision in decisions if decision.get("decision") == "apply")
    lines = [
        "Backlog care.",
        given.unread_line,
        given.summary,
        "Decisions:" if decisions else "No draft reached a gate.",
        *(decision_line(decision) for decision in decisions),
        *ids_line("Waiting for a later run", json_list(given.waiting, "--waiting")),
        *reasons_line("Drafts ignored", objects(json_list(given.ignored, "--ignored")), "id"),
        *ids_line("Picked, but not drafted", json_list(given.undrafted, "--undrafted")),
        *reasons_line(
            "Entries of the issues file skipped",
            objects(json_list(given.skipped_entries, "--skipped-entries")),
            "index",
        ),
    ]
    dropped = given.descriptions_dropped.strip()
    if dropped not in {"", "0"}:
        lines.append(f"Descriptions dropped to fit the read budget, newest first: {dropped}.")
    lines.append(
        f"To apply after the run: {applied}, one issue at a time (/triage step 5)."
        if applied
        else "Nothing to apply: the tracker stays as it is."
    )
    joined = "\n".join(line for line in lines if line)
    return joined if len(joined) <= SUMMARY_CHARS else joined[: SUMMARY_CHARS - len(CUT)] + CUT


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="report.py")
    for name in ("--summary", "--unread-line", "--waiting", "--ignored", "--undrafted"):
        parser.add_argument(name, default="")
    parser.add_argument("--skipped-entries", default="")
    parser.add_argument("--descriptions-dropped", default="")
    given = parser.parse_args(argv)
    try:
        decisions = objects(json_list(sys.stdin.read(), "stdin"))
        summary = summary_of(given, decisions)
    except BadInputError as error:
        print(f"report.py: {error}", file=sys.stderr)
        return 2
    apply = [
        {key: decision.get(key, "") for key in APPLY_KEYS}
        for decision in decisions
        if decision.get("decision") == "apply"
    ]
    skipped = [
        {key: decision.get(key, "") for key in ("id", "note", "approver")}
        for decision in decisions
        if decision.get("decision") != "apply"
    ]
    result = {
        "outcome": "apply" if apply else "report_only",
        "summary": summary,
        "apply": apply,
        "skipped": skipped,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
