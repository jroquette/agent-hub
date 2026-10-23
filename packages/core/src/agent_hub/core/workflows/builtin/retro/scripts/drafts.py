# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Write the changes the owner kept as issue drafts in the hub's inbox, and say how the retro ended.

``drafts.py --nothing BOOL --count N --decision ID --note TEXT --summary TEXT [--today
YYYY-MM-DD]``, run in the hub, reads the ``vet`` step's output on stdin (empty when it did
not run).
An empty value reads as absent (its producer was skipped). The outcome is:

- ``nothing to change`` when step 1 found no run (``--nothing true``) or no change passed the
  evidence check (``--count`` empty or 0);
- ``none kept`` when the owner chose ``none``, or ``keep`` with a note that names no change number
  from 1 to N (the note is numbers such as ``1,3``, or ``all`` alone; ``all`` with other words
  keeps none);
- ``drafted`` otherwise: the kept changes go to ``brain/_inbox/retro-<date>.md`` (``-2`` … ``-9``
  when taken), front matter ``status: to-file``, one section per change with its evidence, then
  the metrics summary. The owner files them in the tracker and runs /triage; nothing here writes
  the tracker.

It prints ``{"outcome", "kept", "path", "summary"}`` (``path`` is ``""`` when no file is
written). Malformed input exits 2; an inbox that is a link, or no free file name, exits 1.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Not datetime.UTC: the hub's copy also imports on Python 3.9.
UTC = timezone.utc  # noqa: UP017

Change = dict[str, object]

NOTHING = "nothing to change"
NONE_KEPT = "none kept"
DRAFTED = "drafted"
MAX_NOTE = 2000
MAX_SUMMARY = 2000
MAX_DRAFT_BYTES = 64 * 1024
MAX_SUFFIX = 9
INBOX = ("brain", "_inbox")
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALL = re.compile(r"\ball\b", re.IGNORECASE)
NUMBER = re.compile(r"\d+")
ANSWER = "answer all alone, or the numbers to keep such as 1,3"


class DraftError(Exception):
    """The draft file cannot be written where it must go."""


def decide(
    *, nothing: bool, count: int | None, decision: str, note: str
) -> tuple[str, list[int], str]:
    """``(outcome, the change numbers kept, why)`` from step 1, the evidence check and the gate."""
    if nothing:
        return NOTHING, [], "no run in the window"
    if not count:
        return NOTHING, [], "no change passed the evidence check"
    if decision == "none":
        return NONE_KEPT, [], "the owner kept none"
    if decision != "keep":
        return NONE_KEPT, [], "no decision from the owner"
    text = note[:MAX_NOTE]
    if text.strip().lower() == "all":
        return DRAFTED, list(range(1, count + 1)), ""
    if ALL.search(text):
        # "all but 2" or "1,3 - not all": guessing either way may draft what the owner did not keep.
        return NONE_KEPT, [], "the note mixes 'all' with other words; " + ANSWER
    picked = sorted({n for n in map(int, NUMBER.findall(text)) if 1 <= n <= count})
    if not picked:
        return NONE_KEPT, [], "no change number understood in the owner's note; " + ANSWER
    return DRAFTED, picked, ""


def _section(change: Change) -> list[str]:
    lines = [f"## {change.get('n')}. {change.get('title')}", "", f"Kind: {change.get('kind')}"]
    lines += ["", str(change.get("change") or ""), "", "Evidence (step 1):"]
    refs = change.get("metrics")
    for ref in refs if isinstance(refs, list) else ():
        if isinstance(ref, dict):
            lines.append(f"- {ref.get('key')} = {ref.get('value')}")
    links = change.get("links")
    if isinstance(links, list) and links:
        lines += ["", "Links:", *(f"- {link}" for link in links)]
    lines += ["", f"Expected effect: {change.get('expected_effect')}"]
    lines += ["", f"How the next retro tells: {change.get('how_to_tell')}", ""]
    return lines


def render(kept: list[Change], *, summary: str, today: date, run_id: str) -> str:
    """The draft file: front matter, one section per kept change, then the metrics summary."""
    sources = f"[.agent-runs/workflows/{run_id}/]" if RUN_ID.match(run_id) else "[]"
    lines = [
        "---",
        "type: issue-drafts",
        "repos: []",
        "status: to-file",
        f"last_verified: {today.isoformat()}",
        f"sources: {sources}",
        "provenance: agent",
        "target: tracker via /triage",
        "---",
        f"# Retro issue drafts ({today.isoformat()})",
        "",
        "The changes the owner kept at the retro's gate. File the ones worth doing in the tracker,",
        "then /triage them; delete this file once they are filed.",
        "",
    ]
    for change in kept:
        lines += _section(change)
    lines += ["## Metrics summary", "", summary.strip(), ""]
    return "\n".join(lines)


def write(root: Path, text: str, today: date) -> Path:
    """``text`` in a new ``brain/_inbox/retro-<today>[-n].md``; its path relative to ``root``."""
    data = text.encode("utf-8")
    if len(data) > MAX_DRAFT_BYTES:
        raise DraftError("the draft is over 64 KiB; no draft written")
    folder = root
    for part in INBOX:
        folder = folder / part
        if folder.is_symlink():
            raise DraftError(f"{'/'.join(INBOX)} is a link; no draft written")
    folder.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    for n in range(1, MAX_SUFFIX + 1):
        name = f"retro-{today.isoformat()}{f'-{n}' * (n > 1)}.md"
        try:
            descriptor = os.open(folder / name, flags, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        return Path(*INBOX, name)
    raise DraftError(f"{MAX_SUFFIX} drafts for {today.isoformat()} exist already; no draft written")


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="drafts.py")
    for flag in ("--nothing", "--count", "--decision", "--note", "--summary", "--today"):
        parser.add_argument(flag, default="")
    return parser.parse_args(argv)


def _count(text: str) -> int | None:
    if not text.strip():
        return None
    if not text.strip().isdigit():
        raise ValueError(f"--count must be a whole number, not {text!r}")
    return int(text)


def _kept(stdin: str, picked: list[int]) -> list[Change]:
    """The vetted changes whose numbers the owner picked."""
    try:
        vetted = json.loads(stdin)
    except ValueError:
        vetted = None
    kept = vetted.get("kept") if isinstance(vetted, dict) else None
    if not isinstance(kept, list):
        raise ValueError("stdin is not the vet step's output")
    return [change for change in kept if isinstance(change, dict) and change.get("n") in picked]


def _result(outcome: str, *, kept: int, path: str, why: str) -> dict[str, object]:
    if outcome == DRAFTED:
        said = f"Drafted {kept} changes to {path}: file them in the tracker, then /triage them."
    else:
        said = f"{outcome.capitalize()}: {why}; no draft written."
    return {"outcome": outcome, "kept": kept, "path": path, "summary": said[:MAX_SUMMARY]}


def main(argv: list[str]) -> int:
    given = _arguments(argv)
    try:
        today = date.fromisoformat(given.today) if given.today else datetime.now(UTC).date()
        count = _count(given.count)
        nothing = given.nothing.strip().lower() == "true"
        outcome, picked, why = decide(
            nothing=nothing, count=count, decision=given.decision.strip(), note=given.note
        )
        kept = _kept(sys.stdin.read(), picked) if outcome == DRAFTED else []
    except ValueError as error:
        print(f"drafts.py: {error}", file=sys.stderr)
        return 2
    path = ""
    if kept:
        text = render(
            kept, summary=given.summary, today=today, run_id=os.environ.get("AGENT_HUB_RUN_ID", "")
        )
        try:
            path = write(Path(), text, today).as_posix()
        except (DraftError, OSError) as error:
            print(f"drafts.py: {error}", file=sys.stderr)
            return 1
    elif outcome == DRAFTED:
        outcome, why = NONE_KEPT, "the picked changes are not in the vet step's output"
    print(json.dumps(_result(outcome, kept=len(kept), path=path, why=why)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
