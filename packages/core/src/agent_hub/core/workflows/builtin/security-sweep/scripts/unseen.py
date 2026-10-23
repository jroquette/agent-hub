# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The findings of a scan not seen before, and marking them seen; one JSON object on stdout.

``unseen.py select`` reads ``scan.py``'s output on stdin and the hub's store of seen findings
(``.agent-runs/security-sweep/seen.json``, gitignored) and prints
``{"findings": [{"id", "fingerprint", <the finding>}], "listed", "counts": {"new", "seen",
"more"}, "ran": [{"repo", "scanner"}], "current": [<fingerprint>], "store_problem"}``: at most
``MAX_LISTED`` new findings in the scan's order (ids ``F1``...), within ``MAX_LISTED_BYTES``; the
rest are counted in ``more`` and stay unseen. It writes nothing.

``unseen.py mark --status <findings|clean> --triaged <JSON list of ids>`` reads that output on
stdin, after the report, and updates the store: a ``(repo, scanner)`` that ran this time keeps
only the entries it still reports (a fixed finding that comes back is new again), one that did
not run keeps its entries, and the listed findings whose id triage named (kept, unresolved or
dropped, as the report read them) are added with today's date; a listed finding triage did not
name stays unseen and comes back next run. Past ``MAX_ENTRIES``, the oldest entries go. The
store is written to a temporary file, then renamed over. It prints ``{"status", "marked",
"store_size"}``.

A fingerprint is ``<repo>/<scanner>/<16 hex>``: the SHA-256 of repo, scanner, rule, path,
package, advisory and the finding's rank among the same ones by line; no line and no code, so a
line shift is not new and nothing in it can be guessed back to a secret line. The known limit
of the rank: a new hit of a seen finding's rule in the same file, at an earlier line, takes the
seen hit's rank, so the seen hit is listed again in its place (triage then sees the old line,
not the new one, until both are listed in a later run). A store that is not
a regular file (a link, a folder), over ``MAX_STORE_BYTES`` or not version 1 reads as empty with
``store_problem`` set; ``mark`` rewrites it. Bad stdin or status exits 2; a store that cannot be
written exits 1. ``--store`` and ``--today`` are for tests.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STORE = ".agent-runs/security-sweep/seen.json"
MAX_STDIN = 2 * 1024 * 1024
MAX_STORE_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_FINDINGS = 1000
MAX_LISTED = 100
# The listing is an argument of the report and, with up to 100 repos, the triage prompt: both
# stay under 128 KiB.
MAX_LISTED_BYTES = 48 * 1024
STORE_PROBLEM = "the seen-findings store could not be read; read as empty"
SCANNERS = {"semgrep", "bandit", "pip-audit", "npm", "guard"}
TEXTS = ("rule", "path", "severity", "cwe", "package", "version", "advisory", "fixed", "title")
REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")
FINGERPRINT = re.compile(r"[A-Za-z0-9._-]{1,100}/[a-z-]{1,10}/[0-9a-f]{16}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
ID = re.compile(r"F[1-9][0-9]{0,2}")
STATUSES = ("findings", "clean")

Finding = dict[str, object]
Seen = dict[str, str]
READ_ERRORS = (OSError, ValueError)


class BadInputError(Exception):
    """Stdin is not what the step reads."""


def canonical(value: object) -> str:
    """The engine's canonical text of a JSON value: compact, sorted keys, UTF-8 unescaped."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(parts: list[str]) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:16]


def fingerprints(findings: list[Finding]) -> list[str]:
    """Each finding's fingerprint, in order (see the module's docstring)."""
    keys = [
        [str(finding[name]) for name in ("repo", "scanner", "rule", "path", "package", "advisory")]
        for finding in findings
    ]
    groups: dict[str, list[int]] = {}
    for index, key in enumerate(keys):
        groups.setdefault("\x00".join(key), []).append(index)
    rank = [0] * len(findings)
    for indexes in groups.values():
        by_line = sorted(indexes, key=lambda index: (line_of(findings[index]), index))
        for occurrence, index in enumerate(by_line):
            rank[index] = occurrence
    return [
        f"{key[0]}/{key[1]}/{digest([*key, str(rank[index])])}" for index, key in enumerate(keys)
    ]


def line_of(finding: Finding) -> int:
    line = finding.get("line")
    return line if isinstance(line, int) else -1


def a_finding(item: object) -> Finding:
    """A finding of ``scan.py``'s shape, or ``BadInputError``."""
    if not isinstance(item, dict):
        raise BadInputError
    repo, scanner, line = item.get("repo"), item.get("scanner"), item.get("line", 0)
    if not (isinstance(repo, str) and REPO.fullmatch(repo) and scanner in SCANNERS):
        raise BadInputError
    if not all(isinstance(item.get(name), str) for name in TEXTS):
        raise BadInputError
    if not (line is None or isinstance(line, int)) or not isinstance(item.get("secret"), bool):
        raise BadInputError
    return item


def a_list(data: dict[str, object], key: str, limit: int) -> list[object]:
    found = data.get(key)
    if not isinstance(found, list) or len(found) > limit:
        raise BadInputError
    return found


def read_stdin() -> dict[str, object]:
    try:
        data = json.loads(sys.stdin.read(MAX_STDIN + 1)[:MAX_STDIN])
    except ValueError:
        raise BadInputError from None
    if not isinstance(data, dict):
        raise BadInputError
    return data


def read_store(path: Path) -> tuple[Seen, str]:
    """The store's entries and a problem (empty when none); a missing store is empty."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {}, ""
    except OSError:
        return {}, STORE_PROBLEM
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STORE_BYTES:
        return {}, STORE_PROBLEM
    try:
        data = json.loads(path.read_bytes())
    except READ_ERRORS:
        return {}, STORE_PROBLEM
    seen = data.get("seen") if isinstance(data, dict) and data.get("version") == 1 else None
    if not isinstance(seen, dict):
        return {}, STORE_PROBLEM
    return {
        key: value
        for key, value in seen.items()
        if isinstance(key, str)
        and FINGERPRINT.fullmatch(key)
        and isinstance(value, str)
        and DATE.fullmatch(value)
    }, ""


def ran_pairs(repos: list[object]) -> list[dict[str, str]]:
    """The ``(repo, scanner)`` pairs that ran, from the scan's repos."""
    pairs = []
    for record in repos:
        if not isinstance(record, dict) or record.get("status") != "scanned":
            continue
        scanners = record.get("scanners")
        for scanner in scanners if isinstance(scanners, list) else []:
            if isinstance(scanner, dict) and scanner.get("status") == "ran":
                pairs.append({"repo": str(record.get("repo")), "scanner": str(scanner.get("name"))})
    return pairs


def listing(fresh: list[tuple[str, Finding]]) -> list[Finding]:
    """The first new findings, ids ``F1``..., within ``MAX_LISTED`` and ``MAX_LISTED_BYTES``."""
    listed: list[Finding] = []
    size = 2
    for fingerprint, finding in fresh[:MAX_LISTED]:
        item = {"id": f"F{len(listed) + 1}", "fingerprint": fingerprint, **finding}
        size += len(canonical(item).encode()) + 1
        if size > MAX_LISTED_BYTES:
            break
        listed.append(item)
    return listed


def select(scan: dict[str, object], store: Path) -> dict[str, object]:
    findings = [a_finding(item) for item in a_list(scan, "findings", MAX_FINDINGS)]
    repos = a_list(scan, "repos", 1000)
    more, trimmed = scan.get("more"), scan.get("trimmed")
    if not (isinstance(more, int) and more >= 0 and isinstance(trimmed, bool)):
        raise BadInputError
    seen, problem = read_store(store)
    prints = fingerprints(findings)
    fresh = [(prints[n], finding) for n, finding in enumerate(findings) if prints[n] not in seen]
    listed = listing(fresh)
    return {
        "findings": listed,
        "listed": len(listed),
        "counts": {
            "new": len(fresh),
            "seen": len(findings) - len(fresh),
            "more": len(fresh) - len(listed) + more,
        },
        # A scan cut at its cap does not show every finding still reported: drop none.
        "ran": [] if more or trimmed else ran_pairs(repos),
        "current": prints,
        "store_problem": problem,
    }


def strings(items: list[object], pattern: re.Pattern[str]) -> list[str]:
    if not all(isinstance(item, str) and pattern.fullmatch(item) for item in items):
        raise BadInputError
    return [str(item) for item in items]


def triaged_prints(selected: dict[str, object], triaged: set[str]) -> list[str]:
    """The fingerprints of the listed findings whose id triage named."""
    listed = [as_dict(item) for item in a_list(selected, "findings", MAX_LISTED)]
    named = [item for item in listed if item.get("id") in triaged]
    return strings([item.get("fingerprint") for item in named], FINGERPRINT)


def marked(selected: dict[str, object], seen: Seen, *, today: str, triaged: set[str]) -> Seen:
    """The store after this run (see the module's docstring)."""
    adds = triaged_prints(selected, triaged)
    current = set(strings(a_list(selected, "current", MAX_FINDINGS), FINGERPRINT))
    ran = {
        f"{as_dict(pair).get('repo')}/{as_dict(pair).get('scanner')}"
        for pair in a_list(selected, "ran", 1000)
    }
    kept = {
        key: day for key, day in seen.items() if key in current or key.rsplit("/", 1)[0] not in ran
    }
    kept.update(dict.fromkeys(adds, today))
    newest = sorted(kept.items(), key=lambda item: (item[1], item[0]), reverse=True)
    return dict(sorted(newest[:MAX_ENTRIES]))


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def write_store(path: Path, seen: Seen) -> None:
    """The store, written to a temporary file beside it, then renamed over it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".seen-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump({"version": 1, "seen": seen}, out)
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def read_ids(text: str | None) -> set[str]:
    """``--triaged``: a JSON list of listing ids, or ``BadInputError``."""
    try:
        ids = json.loads(text) if text is not None else None
    except ValueError:
        raise BadInputError from None
    if not isinstance(ids, list) or len(ids) > 3 * MAX_LISTED:
        raise BadInputError
    return set(strings(ids, ID))


def mark(selected: dict[str, object], *, store: Path, today: str, status: str, ids: str) -> int:
    triaged = read_ids(ids)
    count = len(triaged_prints(selected, triaged))
    seen = marked(selected, read_store(store)[0], today=today, triaged=triaged)
    try:
        write_store(store, seen)
    except OSError as error:
        print(f"unseen.py: cannot write the store: {type(error).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({"status": status, "marked": count, "store_size": len(seen)}))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="unseen.py", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("select", "mark"))
    parser.add_argument("--status", default="", help="the report's status, for mark")
    parser.add_argument("--triaged", default=None, help="the ids triage named (JSON), for mark")
    parser.add_argument("--store", default=STORE, help=argparse.SUPPRESS)
    parser.add_argument("--today", default="", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    today = arguments.today or datetime.now(timezone.utc).date().isoformat()  # noqa: UP017 - 3.9
    if arguments.command == "mark" and arguments.status not in STATUSES:
        print(
            f"unseen.py: the status is not findings or clean: {arguments.status!r}", file=sys.stderr
        )
        return 2
    try:
        data = read_stdin()
        if arguments.command == "select":
            print(json.dumps(select(data, Path(arguments.store))))
            return 0
        return mark(
            data,
            store=Path(arguments.store),
            today=today,
            status=arguments.status,
            ids=arguments.triaged,
        )
    except BadInputError:
        print(f"unseen.py: stdin is not the {arguments.command} input", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
