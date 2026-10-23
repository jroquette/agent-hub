# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Append a post-merge verification run's entries to the hub's inbox; print the verdict as JSON.

``report.py --mode <merge|weekly> --sha <sha> --repo <dir> [--tickets <JSON list>]
[--unreadable <JSON list>] [--truncated <n>] [--explain <JSON>] [--today <YYYY-MM-DD>]``, run in
the hub, reads ``verify.py``'s JSON on stdin; ``--explain`` is the explain step's reply (blank when
it was skipped), ``--today`` stands in for today's UTC date in tests, and the run's id comes from
``AGENT_HUB_RUN_ID``. Each failure is written with its feature, AC, command, status and exit code,
the output's tail, the suspected merge and the evidence explain gave, and a draft ``/fix`` line; a
verification that cannot run after the merge, one not run (budget), a record that could not be
read and the ACs left out by the selection cap are listed apart. Commands and outputs go in fences
longer than any backtick run inside them, with control characters dropped.

The entries go to ``brain/_inbox/verify-YYYY-MM-DD.md`` as one ``## Run <id> at <sha7> (<mode>)``
section, appended when the file exists (its front matter written once). With no entry nothing is
written. Output: ``{"verdict", "entries", "path"}``: ``verdict`` is ``clean`` (no entry),
``regressed`` (a failed, timed-out or unreadable-again verification) or ``attention`` (only
entries that are not failures); ``path`` is blank when nothing was written. Bad input exits 2
with ``report.py: <reason>`` on stderr.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

USAGE = (
    "usage: report.py --mode <merge|weekly> --sha <sha> --repo <dir> [--tickets <json>]"
    " [--unreadable <json>] [--truncated <n>] [--explain <json>] [--today <date>] < run.json"
)
INBOX = Path("brain/_inbox")
MAX_INPUT_BYTES = 1024 * 1024
NAMES = {
    "--mode",
    "--sha",
    "--repo",
    "--tickets",
    "--unreadable",
    "--truncated",
    "--explain",
    "--today",
}
# Every control character but the newline and the tab, for multi-line text in a fence.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# Every control character, for text on one line.
LINE_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
BACKTICKS = re.compile(r"`+")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class BadInputError(Exception):
    """The input is not what the report step reads."""


@dataclass(frozen=True)
class Meta:
    """The run's facts the report states: its id, mode, commit, repo and selection's leftovers."""

    run_id: str
    mode: str
    sha: str
    repo: str
    tickets: list[object]
    unreadable: list[object]
    truncated: int


def line(text: object) -> str:
    return LINE_CONTROL.sub("", str(text))


def fenced(text: str) -> str:
    """``text`` in a ``text`` fence longer than any backtick run inside it."""
    clean = CONTROL.sub("", text).rstrip("\n")
    longest = max((len(run) for run in BACKTICKS.findall(clean)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{clean}\n{fence}"


def suspects_of(explain: dict[str, object]) -> dict[tuple[str, str], dict[str, object]]:
    found = explain.get("suspects")
    return {
        (str(item.get("feature")), str(item.get("ac"))): item
        for item in (found if isinstance(found, list) else [])
        if isinstance(item, dict)
    }


def failure_block(failure: dict[str, object], suspect: dict[str, object] | None, sha7: str) -> str:
    feature, ac = line(failure.get("feature")), line(failure.get("ac"))
    status, code = line(failure.get("status")), failure.get("exit_code")
    how = {"failed": f"exit {code}", "timeout": "timed out"}.get(status, "could not be read again")
    parts = [
        f"#### {feature} {ac}: {status}, {how}",
        "",
        f"Last passed: {line(failure.get('since')) or 'unknown'}.",
        "",
        "Command:",
        "",
        fenced(str(failure.get("command", ""))),
        "",
        "Output (tail):",
        "",
        fenced(str(failure.get("tail", ""))),
        "",
    ]
    parts.extend(suspect_lines(suspect))
    merge = line(suspect.get("merge")) if suspect else ""
    blame = f"; suspect {merge[:7]}" if merge else ""
    parts.append(
        f"Draft: /fix (or /change) {feature} {ac}: its verification {how} at {sha7}{blame}."
    )
    return "\n".join(parts)


def suspect_lines(suspect: dict[str, object] | None) -> list[str]:
    if suspect is None:
        return ["Suspect: none named (explain did not run).", ""]
    if not suspect:
        return ["Suspect: none found (explain named no merge for this AC).", ""]
    kind = line(suspect.get("kind"))
    merge = line(suspect.get("merge"))[:7]
    found = [
        f"Suspect: {merge or 'none'} {line(suspect.get('subject'))} ({kind}).".replace("  ", " ")
    ]
    if kind == "flaky":
        found.append(
            "Flaky: no merge since the last pass touches what it tests; the failure stays."
        )
    found.extend([f"Evidence: {line(suspect.get('evidence'))}", ""])
    return found


def cannot_run_lines(run: dict[str, object]) -> list[str]:
    listed = run.get("cannot_run")
    items = listed if isinstance(listed, list) else []
    found = ["### Cannot run after merge", ""]
    for item in items:
        if isinstance(item, dict):
            found.extend(
                [
                    f"- {line(item.get('feature'))} {line(item.get('ac'))}"
                    f" ({line(item.get('reason'))}):",
                    "",
                    fenced(str(item.get("command", ""))),
                    "",
                ]
            )
    if more := number(run.get("more_cannot_run")):
        found.extend([f"And {more} more.", ""])
    return found


def number(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def counts_of(run: dict[str, object]) -> dict[str, int]:
    counts = run.get("counts")
    given = counts if isinstance(counts, dict) else {}
    keys = ("selected", "passed", "failed", "timed_out", "errors", "cannot_run", "not_run")
    return {key: number(given.get(key)) for key in keys}


def failed_lines(
    run: dict[str, object], explain: dict[str, object], *, broken: int, sha7: str
) -> list[str]:
    failures, more = run.get("failures"), run.get("more_failed")
    suspects = suspects_of(explain)
    found = ["### Failed", ""]
    detailed = 0
    for failure in failures if isinstance(failures, list) else []:
        if isinstance(failure, dict):
            detailed += 1
            key = (str(failure.get("feature")), str(failure.get("ac")))
            # None: explain did not run; {}: it ran and named no suspect for this AC.
            suspect = suspects.get(key, {}) if explain else None
            found.extend([failure_block(failure, suspect, sha7), ""])
    if broken > detailed:
        # The run names the rest while its output has room; the count holds them all.
        names = ", ".join(line(item) for item in more) if isinstance(more, list) else ""
        found.extend([f"And {broken - detailed} more failed{': ' + names if names else ''}.", ""])
    return found


def leftovers(counts: dict[str, int], meta: Meta) -> tuple[list[str], int]:
    """The not-run, unreadable and cap sections, and how many entries they hold."""
    found, entries = [], 0
    if counts["not_run"]:
        found.extend(
            ["### Not run", "", f"{counts['not_run']} not run: the run's budget was spent.", ""]
        )
        entries += counts["not_run"]
    if meta.unreadable:
        found.extend(["### Could not read", ""])
        for item in meta.unreadable:
            given = item if isinstance(item, dict) else {}
            found.append(f"- {line(given.get('path'))}: {line(given.get('reason'))}")
        found.append("")
        entries += len(meta.unreadable)
    if meta.truncated:
        found.extend(["### Not selected", "", f"{meta.truncated} ACs not selected (cap).", ""])
        entries += meta.truncated
    return found, entries


def render(run: dict[str, object], explain: dict[str, object], meta: Meta) -> tuple[str, int, str]:
    """The run's verdict, its entry count and its markdown section."""
    counts = counts_of(run)
    broken = counts["failed"] + counts["timed_out"] + counts["errors"]
    sha7 = meta.sha[:7]
    sections: list[str] = []
    if broken:
        sections.extend(failed_lines(run, explain, broken=broken, sha7=sha7))
    if counts["cannot_run"]:
        sections.extend(cannot_run_lines(run))
    rest, others = leftovers(counts, meta)
    sections.extend(rest)
    entries = broken + counts["cannot_run"] + others
    verdict = "regressed" if broken else ("attention" if entries else "clean")
    tickets = ", ".join(line(item) for item in meta.tickets) or "none"
    scope = f"tickets {tickets}" if meta.mode == "merge" else "every passing AC"
    summary = (
        f"Repo `{line(meta.repo)}`, {scope}. {counts['selected']} selected: {counts['passed']}"
        f" passed, {counts['failed']} failed, {counts['timed_out']} timed out, {counts['errors']}"
        f" could not be read again, {counts['cannot_run']} cannot run after merge,"
        f" {counts['not_run']} not run. Verdict: {verdict}."
    )
    head = f"## Run {line(meta.run_id) or 'unknown'} at {sha7} ({line(meta.mode)})"
    markdown = "\n".join([head, "", summary, "", *sections]).rstrip("\n") + "\n"
    return verdict, entries, markdown


def options(argv: list[str]) -> dict[str, str]:
    given = dict(zip(argv[::2], argv[1::2], strict=False))
    required = {"--mode", "--sha", "--repo"}
    if len(argv) % 2 or not set(given) <= NAMES or not required <= set(given):
        raise BadInputError(USAGE)
    if given["--mode"] not in {"merge", "weekly"}:
        raise BadInputError(f"unknown mode {given['--mode']!r}")
    return given


def parsed(text: str, kind: type, what: str) -> object:
    """``text`` as JSON of ``kind`` (blank: an empty one)."""
    if not text.strip():
        return kind()
    try:
        value = json.loads(text)
    except ValueError:
        raise BadInputError(f"{what} is not JSON") from None
    if not isinstance(value, kind):
        raise BadInputError(f"{what} is not a JSON {kind.__name__}")
    return value


def inputs(given: dict[str, str], stdin: str) -> tuple[dict[str, object], dict[str, object], Meta]:
    run = parsed(stdin, dict, "stdin")
    explain = parsed(given.get("--explain", ""), dict, "--explain")
    tickets = parsed(given.get("--tickets", ""), list, "--tickets")
    unreadable = parsed(given.get("--unreadable", ""), list, "--unreadable")
    truncated = given.get("--truncated", "") or "0"
    if not (truncated.isascii() and truncated.isdecimal()):
        raise BadInputError(f"--truncated is not a count: {truncated!r}")
    if not isinstance(run, dict) or not isinstance(explain, dict):
        raise BadInputError(USAGE)
    if not isinstance(tickets, list) or not isinstance(unreadable, list):
        raise BadInputError(USAGE)
    meta = Meta(
        run_id=os.environ.get("AGENT_HUB_RUN_ID", ""),
        mode=given["--mode"],
        sha=given["--sha"],
        repo=given["--repo"],
        tickets=tickets,
        unreadable=unreadable,
        truncated=int(truncated),
    )
    return run, explain, meta


def today(given: dict[str, str]) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)  # noqa: UP017 - 3.9 has no datetime.UTC
    day = given.get("--today") or now.date().isoformat()
    if not DAY.fullmatch(day):
        raise BadInputError(f"--today is not a date: {day!r}")
    return day


def write(day: str, markdown: str) -> Path:
    path = INBOX / f"verify-{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        # A resumed run's report step may run again: its section is written once.
        if markdown.splitlines()[0] in path.read_text(encoding="utf-8").splitlines():
            return path
        with path.open("a", encoding="utf-8") as report:
            report.write("\n" + markdown)
        return path
    front = (
        "---\ntype: verify-report\nstatus: proposed\n"
        f"last_verified: {day}\nprovenance: agent\n---\n"
        f"# Post-merge verification, {day}\n\n"
    )
    path.write_text(front + markdown, encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    try:
        given = options(argv)
        day = today(given)
        run, explain, meta = inputs(given, sys.stdin.read(MAX_INPUT_BYTES + 1))
    except BadInputError as error:
        print(f"report.py: {error}", file=sys.stderr)
        return 2
    verdict, entries, markdown = render(run, explain, meta)
    path = write(day, markdown).as_posix() if entries else ""
    print(json.dumps({"verdict": verdict, "entries": entries, "path": path}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
