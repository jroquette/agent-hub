# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Write the security sweep's note for /triage in ``brain/_inbox/`` and print what it holds.

``report.py --findings <new's listing> --repos <scan's repos> --counts <new's counts>
[--store-problem <text>]``, run in the hub, with the triage reply (``{"kept", "unresolved",
"dropped"}``) on stdin, blank when triage was skipped (nothing new). The note is
``brain/_inbox/security-YYYY-MM-DD.md`` (UTC), or with the run's first 8 characters
(``AGENT_HUB_RUN_ID``, else ``local``) and then a number when that name is taken: never
overwritten. It names each repo's scanned commit and each scanner's end, lists only the findings
triage kept (an id not in the listing is ignored and counted), then the unresolved ones, the
listed findings triage named nowhere (kept, unresolved or dropped) with the mismatch flagged, and
the counts. A finding's rule, path and line come from the listing, never from the agent; the agent's
text is one quoted line (control characters dropped, backticks replaced, ``MAX_TEXT`` characters).
A secret finding is its rule and path with a fixed text: the agent's text for it is never written.

Output: ``{"path", "kept", "secrets", "missing": ["<repo>: <scanner>"], "triaged": [<id>],
"status"}``: ``triaged`` the listed ids triage named, the only ones ``mark`` marks seen;
``status`` ``findings`` when triage kept one, else ``clean``. Bad input exits 2 and writes nothing.
``--today`` is for tests.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

INBOX = Path("brain") / "_inbox"
MAX_STDIN = 2 * 1024 * 1024
MAX_TEXT = 400
MAX_MISSING = 100
MAX_NAMES = 100
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
RUN = re.compile(r"[^A-Za-z0-9_-]")
LEAK_NOTE = (
    "A credential may be committed at this path; its value is not shown. Fix: remove it from the"
    " code and its history, rotate it, and read it from the environment or a secret store."
)
CLOSING = "No tracker write. File an issue for each finding you accept, then run /triage <issue>."

Item = dict[str, object]


class BadInputError(Exception):
    """An argument or stdin is not what the step reads; the message names it."""


def one_line(text: object, limit: int = MAX_TEXT) -> str:
    """Text for one markdown line: line breaks as spaces, other control and format characters
    dropped, backticks replaced, cut to ``limit``."""
    spaced = re.sub(r"[\r\n\t  ]+", " ", text if isinstance(text, str) else "")
    kept = "".join(char for char in spaced if not unicodedata.category(char).startswith("C"))
    return kept.replace("`", "'").strip()[:limit]


def code(text: object) -> str:
    return f"`{one_line(text, 300)}`"


def parsed(text: str, what: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        raise BadInputError(f"{what} is not JSON") from None


def json_object(text: str, what: str) -> Item:
    value = parsed(text, what)
    if not isinstance(value, dict):
        raise BadInputError(f"{what} is not a JSON object")
    return value


def objects(values: object, what: str) -> list[Item]:
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise BadInputError(f"{what} is not a list of objects")
    return values


def read_triage(text: str) -> Item:
    """The triage reply; blank (triage skipped) keeps nothing."""
    if not text.strip():
        return {"kept": [], "unresolved": [], "dropped": []}
    return json_object(text, "the triage reply")


def where(finding: Item) -> str:
    """``[severity] `rule` - `path:line` (scanner, repo)``; a secret one has no line."""
    if finding.get("secret") is True:
        label, place = "secret", code(finding.get("path"))
    else:
        line = finding.get("line")
        label = one_line(finding.get("severity"), 20)
        suffix = f":{line}" if isinstance(line, int) else ""
        place = code(f"{one_line(finding.get('path'), 300)}{suffix}")
    source = one_line(f"{finding.get('scanner')}, {finding.get('repo')}", 140)
    return f"[{label}] {code(finding.get('rule'))} - {place} ({source})"


def scanner_line(scanner: Item) -> str:
    name, state = one_line(scanner.get("name"), 20), one_line(scanner.get("status"), 20)
    note = one_line(scanner.get("note"), 200)
    if state == "ran":
        return f"  - {name}: ran ({scanner.get('count')})"
    if state == "missing":
        return f"  - {name}: missing - {note or 'not installed'}"
    return f"  - {name}: {state} ({note})"


def scanned(repos: list[Item]) -> list[str]:
    lines = ["## Scanned", ""]
    for repo in repos:
        name = code(repo.get("repo"))
        if repo.get("status") != "scanned":
            lines.append(f"- {name}: unreadable - {one_line(repo.get('note'), 200)}")
            continue
        head, date = one_line(repo.get("head"), 7), one_line(repo.get("date"), 40)
        lines.append(f"- {name} as of {code(repo.get('ref'))} `{head}` ({date})")
        scanners = repo.get("scanners")
        lines += [scanner_line(item) for item in objects(scanners, "a repo's scanners")]
    lines += [
        "",
        "npm audit reads package-lock.json only: yarn.lock and pnpm-lock.yaml are not audited.",
        "",
    ]
    return lines


def missing(repos: list[Item]) -> list[str]:
    found = [
        f"{one_line(repo.get('repo'), 100)}: {one_line(scanner.get('name'), 20)}"
        for repo in repos
        for scanner in objects(repo.get("scanners", []), "a repo's scanners")
        if scanner.get("status") == "missing"
    ]
    return found[:MAX_MISSING]


class Picked:
    """The triage reply's entries whose id is in the listing, each id once; the rest counted."""

    def __init__(self, entries: object, listing: dict[str, Item]) -> None:
        self.found: list[tuple[Item, Item]] = []
        self.ignored = 0
        named: set[str] = set()
        for entry in entries if isinstance(entries, list) else []:
            key = entry.get("id") if isinstance(entry, dict) else None
            if isinstance(key, str) and key in listing and key not in named:
                named.add(key)
                self.found.append((listing[key], entry))
            elif not (isinstance(key, str) and key in named):
                self.ignored += 1


def kept_lines(picked: Picked) -> list[str]:
    lines = ["## Findings for /triage", ""]
    for n, (finding, entry) in enumerate(picked.found, start=1):
        lines.append(f"{n}. {where(finding)}")
        if finding.get("secret") is True:
            lines.append(f"   > {LEAK_NOTE}")
        else:
            lines.append(f"   > Attack: {one_line(entry.get('attack'))}")
            lines.append(f"   > Fix: {one_line(entry.get('fix'))}")
    return [*lines, *(() if picked.found else ("No finding kept.",)), ""]


def unresolved_lines(picked: Picked) -> list[str]:
    if not picked.found:
        return []
    lines = ["## Unresolved", ""]
    for finding, entry in picked.found:
        why = "not settled by triage" if finding.get("secret") is True else entry.get("why")
        lines += [f"- {where(finding)}", f"  > {one_line(why, 300)}"]
    return [*lines, ""]


def ids_as_entries(values: object) -> list[object]:
    """``dropped``, a list of ids, as entries ``Picked`` reads."""
    return [{"id": value} for value in values] if isinstance(values, list) else []


class Triage:
    """The reply read against the listing: each part's entries, and the listed findings triage
    named in none of them (it stopped short: they stay unseen and come back next run)."""

    def __init__(self, reply: Item, findings: list[Item]) -> None:
        listing = {str(finding.get("id")): finding for finding in findings}
        self.kept = Picked(reply.get("kept"), listing)
        self.unresolved = Picked(reply.get("unresolved"), listing)
        self.dropped = Picked(ids_as_entries(reply.get("dropped")), listing)
        parts = (self.kept, self.unresolved, self.dropped)
        named = {str(finding.get("id")) for part in parts for finding, _ in part.found}
        self.triaged = [key for key in listing if key in named]
        self.untriaged = [finding for key, finding in listing.items() if key not in named]
        self.ignored = sum(part.ignored for part in parts)


def untriaged_lines(triage: Triage) -> list[str]:
    if not triage.untriaged:
        return []
    lines = ["## Not triaged", ""]
    lines += [f"- {where(finding)}" for finding in triage.untriaged]
    return [*lines, ""]


def count_lines(counts: Item, triage: Triage) -> list[str]:
    seen = (
        f"New: {counts.get('new')}; kept: {len(triage.kept.found)};"
        f" dropped: {len(triage.dropped.found)};"
        f" unresolved: {len(triage.unresolved.found)}; already seen: {counts.get('seen')};"
        f" not listed, for next run: {counts.get('more')}."
    )
    lines = ["## Counts", "", f"- {seen}"]
    if triage.untriaged:
        listed = len(triage.triaged) + len(triage.untriaged)
        lines.append(
            f"- Triage accounted for {len(triage.triaged)} of {listed} listed findings; the"
            f" other {len(triage.untriaged)} stay unseen and come back next run."
        )
    if triage.ignored:
        plural = "id that is" if triage.ignored == 1 else "ids that are"
        lines.append(f"- Triage named {triage.ignored} {plural} not in the listing; ignored.")
    return [*lines, ""]


def render(findings: list[Item], reply: Item, **given: object) -> tuple[str, str, Item]:
    """``(status, markdown, output fields)`` of the note; ``given`` holds ``repos``,
    ``counts``, ``today`` and ``store_problem``."""
    repos = objects(given["repos"], "the repos")
    counts = given["counts"] if isinstance(given["counts"], dict) else {}
    triage = Triage(reply, findings)
    names = ", ".join(one_line(repo.get("repo"), 100) for repo in repos[:MAX_NAMES])
    lines = [
        "---",
        "type: security-sweep",
        "status: open",
        "provenance: agent",
        f"last_verified: {given['today']}",
        f"repos: [{names}]",
        "---",
        f"# Security sweep {given['today']}",
        "",
        "The scanners read each repo at the commit named below, as last fetched: the sweep does"
        " not fetch. The findings are the new ones the security-reviewer triage kept.",
        "",
        *scanned(repos),
        *kept_lines(triage.kept),
        *unresolved_lines(triage.unresolved),
        *untriaged_lines(triage),
        *count_lines(counts, triage),
    ]
    if given.get("store_problem"):
        lines += [f"Store: {one_line(given['store_problem'], 200)}.", ""]
    lines.append(CLOSING)
    kept = triage.kept.found
    status = "findings" if kept else "clean"
    secrets = sum(1 for finding, _ in kept if finding.get("secret") is True)
    fields: Item = {
        "kept": len(kept),
        "secrets": secrets,
        "missing": missing(repos),
        "triaged": triage.triaged,
    }
    return status, "\n".join(lines) + "\n", fields


def run_label() -> str:
    found = RUN.sub("", os.environ.get("AGENT_HUB_RUN_ID", ""))[:8]
    return found or "local"


def write_note(text: str, today: str) -> Path:
    """The note in a new file: today's name, else with the run's label, then a number."""
    INBOX.mkdir(parents=True, exist_ok=True)
    label = run_label()
    names = [f"security-{today}.md", f"security-{today}-{label}.md"]
    names += [f"security-{today}-{label}-{n}.md" for n in range(2, 100)]
    for name in names:
        path = INBOX / name
        try:
            with path.open("x", encoding="utf-8") as out:
                out.write(text)
        except FileExistsError:
            continue
        return path
    raise FileExistsError(str(INBOX))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="report.py", description=__doc__.split("\n")[0])
    parser.add_argument("--findings", required=True, help="new's listing (JSON)")
    parser.add_argument("--repos", required=True, help="scan's repos (JSON)")
    parser.add_argument("--counts", required=True, help="new's counts (JSON)")
    parser.add_argument("--store-problem", default="", help="new's store problem")
    parser.add_argument("--today", default="", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    today = arguments.today or datetime.now(timezone.utc).date().isoformat()  # noqa: UP017 - 3.9
    try:
        if not DATE.fullmatch(today):
            raise BadInputError("the date is not YYYY-MM-DD")
        findings = objects(parsed(arguments.findings, "the findings"), "the findings")
        status, text, fields = render(
            findings,
            read_triage(sys.stdin.read(MAX_STDIN)),
            repos=objects(parsed(arguments.repos, "the repos"), "the repos"),
            counts=json_object(arguments.counts, "the counts"),
            today=today,
            store_problem=arguments.store_problem,
        )
    except BadInputError as error:
        print(f"report.py: {error}", file=sys.stderr)
        return 2
    path = write_note(text, today)
    print(json.dumps({"path": path.as_posix(), **fields, "status": status}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
