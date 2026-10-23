# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Write a flaky run's counts and likely cause to the hub's inbox; print the outcome as JSON.

``report.py --classification <JSON> [--today <YYYY-MM-DD>]``, run in the hub, reads
``repeat.py``'s JSON on stdin; ``--classification`` is the classify step's reply (blank when it was
skipped), ``--today`` stands in for today's UTC date in tests, and the run's id comes from
``AGENT_HUB_RUN_ID`` (unset or blank exits 2: the section heading names the run).

The note is ``brain/_inbox/flaky-<slug>.md``, one per test: ``<slug>`` is the test id lowercased,
each run of other characters than ``a-z`` and ``0-9`` made one ``-``, cut to 80 characters, then
``-`` and the first 8 hex digits of the id's SHA-256. Each run appends one ``## Run <id> at
<sha7>`` section (the front matter is written once): the test, repo, commit, runner and runs, a
table of counts per mode with the skipped modes named, the outcome (a file or folder run that
timed out or printed no line for the test is named inconclusive, and xfail or xpass results
skipped), the cause, shared state, confidence and evidence classify gave, a next step
(classify's, else a fixed one per cause) and the failing runs' output tails, in fences longer than
any backtick run inside them, with control characters dropped. A section already in the note is
not written again, so a rerun of the same run leaves the file as it was. A note, ``brain`` or
``brain/_inbox`` that is a link, or a note over 256 KiB, exits 1.

Output: ``{"outcome", "path"}``: ``outcome`` is ``reproduced`` (the test failed or erred in a
run, or timed out alone) or ``not_reproduced``. Bad input exits 2 with ``report.py: <reason>`` on
stderr.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

USAGE = "usage: report.py --classification <json> [--today <YYYY-MM-DD>] < run.json"
NAMES = frozenset({"--classification", "--today"})
INBOX = ("brain", "_inbox")
MAX_INPUT_BYTES = 64 * 1024
MAX_NOTE_BYTES = 256 * 1024
SLUG_CHARS = 80
COUNTS = ("passed", "failed", "errors", "timed_out", "missing", "skipped", "not_run")
# The table's columns; skipped results get a line of their own.
TABLE = ("passed", "failed", "errors", "timed_out", "missing", "not_run")
HEADERS = ("Passed", "Failed", "Errors", "Timed out", "Missing", "Not run")
NOT_ALNUM = re.compile(r"[^a-z0-9]+")
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# Every control character but the newline and the tab, for multi-line text in a fence.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# Every control character, for text on one line.
LINE_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
BACKTICKS = re.compile(r"`+")
AGAIN = "Raise runs, or run it under the check gate's load, and read the tails again."
# The next step per cause when classify names none.
NEXT_STEPS = {
    "order_dependence": (
        "Find the test that leaves the state behind (bisect the tests before it in the file)"
        " and reset that state in a fixture."
    ),
    "timing": (
        "Wait on the condition the test needs instead of a sleep or a wall-clock bound,"
        " or widen the bound it asserts."
    ),
    "shared_state": (
        "Give the test its own copy of what it shares (tmp_path, monkeypatch, a fresh process)"
        " and reset it in teardown."
    ),
    "external": "Stub the network, clock or tool the test reaches, or run it only where it is.",
    "unknown": AGAIN,
}


class BadInputError(Exception):
    """The input is not what the report step reads."""


class NoteError(Exception):
    """The note cannot be written safely."""


def line(text: object) -> str:
    return LINE_CONTROL.sub("", str(text))


def cell(text: object) -> str:
    return line(text).replace("|", "\\|")


def code_span(text: object) -> str:
    """``text`` in a code span longer than any backtick run inside it."""
    clean = line(text)
    longest = max((len(run) for run in BACKTICKS.findall(clean)), default=0)
    ticks = "`" * (longest + 1)
    pad = " " if clean.startswith("`") or clean.endswith("`") else ""
    return f"{ticks}{pad}{clean}{pad}{ticks}"


def fenced(text: str) -> str:
    """``text`` in a ``text`` fence longer than any backtick run inside it."""
    clean = CONTROL.sub("", text).rstrip("\n")
    longest = max((len(run) for run in BACKTICKS.findall(clean)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{clean}\n{fence}"


def slug(test: str) -> str:
    """The note's name for ``test``: only ``a-z``, ``0-9`` and ``-``, so it stays in the inbox."""
    base = NOT_ALNUM.sub("-", test.lower()).strip("-")[:SLUG_CHARS].strip("-")
    digest = hashlib.sha256(test.encode(errors="surrogatepass")).hexdigest()[:8]
    return f"{base}-{digest}" if base else digest


def number(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def modes_of(run: dict[str, object]) -> list[dict[str, object]]:
    modes = run.get("modes")
    return [item for item in (modes if isinstance(modes, list) else []) if isinstance(item, dict)]


def table(modes: list[dict[str, object]]) -> list[str]:
    found = [
        "| Mode | Status | " + " | ".join(HEADERS) + " |",
        "|" + " --- |" * (len(HEADERS) + 2),
    ]
    for mode in modes:
        status = "ran" if mode.get("status") == "ran" else "skipped"
        counts = " | ".join(str(number(mode.get(key))) for key in TABLE)
        found.append(f"| {cell(mode.get('mode'))} | {status} | {counts} |")
    found.append("")
    for mode in modes:
        if mode.get("status") != "ran":
            found.append(f"Skipped: {line(mode.get('mode'))} ({line(mode.get('note'))}).")
        else:
            found.append(f"- {line(mode.get('mode'))}: {line(mode.get('note'))}.")
    return [*found, ""]


def ran_count(mode: dict[str, object]) -> int:
    return sum(number(mode.get(key)) for key in COUNTS[:-1])


def inconclusive_lines(modes: list[dict[str, object]]) -> list[str]:
    """The file and folder runs that timed out or lost the test's line, and the skipped results."""
    found: list[str] = []
    unsure = [
        f"{line(mode.get('mode'))} {number(mode.get('timed_out')) + number(mode.get('missing'))}"
        f" of {ran_count(mode)}"
        for mode in modes
        if mode.get("mode") != "alone"
        and number(mode.get("timed_out")) + number(mode.get("missing"))
    ]
    if unsure:
        found.append(
            f"Inconclusive: {', '.join(unsure)} (the file or folder run timed out or printed no"
            " line for the test, not the test's own result)."
        )
    skipped = [
        f"{line(mode.get('mode'))} {number(mode.get('skipped'))}"
        for mode in modes
        if number(mode.get("skipped"))
    ]
    if skipped:
        found.append(f"Skipped results (xfail, xpass or skip): {', '.join(skipped)}.")
    return found


def outcome_lines(run: dict[str, object], modes: list[dict[str, object]]) -> list[str]:
    found: list[str] = []
    if run.get("reproduced") is True:
        found.append("Outcome: reproduced.")
    else:
        ran = [mode for mode in modes if mode.get("status") == "ran"]
        each = ", ".join(
            f"{line(mode.get('mode'))} {number(mode.get('passed'))} of {ran_count(mode)}"
            for mode in ran
        )
        clean = all(number(mode.get("passed")) == ran_count(mode) for mode in ran)
        what = "every run passed" if clean else "no run of the test failed"
        found.append(f"Outcome: not reproduced: {what} ({each}).")
    found.extend(inconclusive_lines(modes))
    if run.get("budget_spent") is True:
        left = sum(number(mode.get("not_run")) for mode in modes)
        found.append(f"The run's budget was spent: {left} runs not run.")
    return [*found, ""]


def cause_lines(run: dict[str, object], classification: dict[str, object]) -> list[str]:
    if run.get("reproduced") is not True:
        return [f"Next step: {AGAIN}", ""]
    cause = line(classification.get("cause", ""))
    given = line(classification.get("next_step", ""))
    if not cause:
        return [
            "Cause: not classified (the classify step did not run or gave nothing).",
            "",
            f"Next step: {given or AGAIN}",
            "",
        ]
    return [
        f"Cause: {cause} (confidence {line(classification.get('confidence', 'unknown'))}).",
        "",
        f"Shared state: {line(classification.get('shared', 'none'))}.",
        "",
        f"Evidence: {line(classification.get('evidence', ''))}",
        "",
        f"Next step: {given or NEXT_STEPS.get(cause, AGAIN)}",
        "",
    ]


def tail_lines(modes: list[dict[str, object]]) -> list[str]:
    found: list[str] = []
    for mode in modes:
        tails = mode.get("tails")
        listed = [item for item in (tails if isinstance(tails, list) else []) if item]
        if listed:
            found.extend([f"#### {line(mode.get('mode'))}", ""])
            for tail in listed:
                found.extend([fenced(str(tail)), ""])
    return ["### Failing runs (tails)", "", *found] if found else []


def render(run: dict[str, object], classification: dict[str, object], run_id: str) -> str:
    modes = modes_of(run)
    runner = run.get("runner")
    sha = str(run["sha"])
    head = f"## Run {line(run_id)} at {sha[:7]}"
    parts = [
        head,
        "",
        f"Test: {code_span(run['test'])}",
        f"Repo: {code_span(run.get('repo', ''))}",
        f"Commit: {code_span(sha)}",
        "Runner: " + code_span(" ".join(str(item) for item in runner))
        if isinstance(runner, list)
        else "Runner: unknown",
        f"Runs per mode: {number(run.get('runs'))}.",
        "",
        *table(modes),
        *outcome_lines(run, modes),
        *cause_lines(run, classification),
        *tail_lines(modes),
    ]
    return "\n".join(parts).rstrip("\n") + "\n"


def options(argv: list[str]) -> dict[str, str]:
    given = dict(zip(argv[::2], argv[1::2], strict=False))
    if len(argv) % 2 or not set(given) <= NAMES or "--classification" not in given:
        raise BadInputError(USAGE)
    return given


def read_run(stdin: str) -> dict[str, object]:
    if len(stdin.encode(errors="surrogatepass")) > MAX_INPUT_BYTES:
        raise BadInputError("stdin is over 64 KiB")
    try:
        run = json.loads(stdin)
    except ValueError:
        raise BadInputError("stdin is not JSON") from None
    if not (
        isinstance(run, dict)
        and isinstance(run.get("test"), str)
        and isinstance(run.get("sha"), str)
        and SHA.fullmatch(run["sha"])
    ):
        raise BadInputError("stdin is not a repeat run: test and a commit sha are needed")
    return run


def read_classification(text: str) -> dict[str, object]:
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        raise BadInputError("--classification is not JSON") from None
    if not isinstance(value, dict):
        raise BadInputError("--classification is not a JSON object")
    return value


def today(given: dict[str, str]) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)  # noqa: UP017 - 3.9 has no datetime.UTC
    day = given.get("--today") or now.date().isoformat()
    if not DAY.fullmatch(day):
        raise BadInputError(f"--today is not a date: {day[:20]!r}")
    return day


def inbox() -> Path:
    """``brain/_inbox``, made when missing; never through a link."""
    folder = Path()
    for part in INBOX:
        folder = folder / part
        if folder.is_symlink():
            raise NoteError(f"{folder.as_posix()} is a link; no note written")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write(path: Path, *, section: str, day: str) -> None:
    """``section`` appended to the note at ``path`` (made with its front matter when missing)."""
    if path.is_symlink():
        raise NoteError(f"{path.as_posix()} is a link; no note written")
    if path.exists():
        if not path.is_file() or path.stat().st_size > MAX_NOTE_BYTES:
            raise NoteError(f"{path.as_posix()} is over 256 KiB or not a file; no note written")
        # A resumed run's report step may run again: its section is written once.
        if section.splitlines()[0] in path.read_text(encoding="utf-8").splitlines():
            return
        text = "\n" + section
        flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
    else:
        front = (
            "---\ntype: flaky\nstatus: proposed\n"
            f"last_verified: {day}\nprovenance: agent\n---\n"
            "# Flaky test runs\n\n"
            "One section per run of the flaky workflow on this test.\n\n"
        )
        text = front + section
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as note:
        note.write(text)


def main(argv: list[str]) -> int:
    try:
        given = options(argv)
        day = today(given)
        classification = read_classification(given["--classification"])
        run = read_run(sys.stdin.read(MAX_INPUT_BYTES + 1))
        run_id = os.environ.get("AGENT_HUB_RUN_ID", "")
        if not line(run_id).strip():
            # The section heading names the run: without it, a rerun guard cannot tell runs apart.
            raise BadInputError("AGENT_HUB_RUN_ID is not set: the run's section needs its id")
    except BadInputError as error:
        print(f"report.py: {error}", file=sys.stderr)
        return 2
    section = render(run, classification, run_id)
    try:
        path = inbox() / f"flaky-{slug(str(run['test']))}.md"
        write(path, section=section, day=day)
    except (NoteError, OSError) as error:
        print(f"report.py: {error}", file=sys.stderr)
        return 1
    outcome = "reproduced" if run.get("reproduced") is True else "not_reproduced"
    print(json.dumps({"outcome": outcome, "path": path.as_posix()}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
