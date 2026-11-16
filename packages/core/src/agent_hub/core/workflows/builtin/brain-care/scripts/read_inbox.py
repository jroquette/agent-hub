# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""List the hub's inbox notes a brain-care ``inbox`` run reviews, as JSON.

``read_inbox.py [--root HUB] [--today YYYY-MM-DD]`` reads ``brain/_inbox/*.md`` (no sub-folder,
no dot file) whose front matter ``status`` is ``proposed`` or absent, oldest name first, at most
50 per run; the rest wait for the next run and are counted in ``omitted``. Each note is read
only when it is a regular file (no link) of at most 256 KiB in UTF-8 with at most 64 front
matter lines; any other is listed in ``unreadable`` with the reason. A note's ``excerpt`` is its
body, control characters removed, cut at 1,500 characters; the ``notes`` list stays within
96 KiB (trailing notes move to ``omitted``), so the grouping prompt stays small.

A note is ``external`` unless its ``provenance`` is ``agent``, ``agent-from-code`` or ``human``
(none counts as external): such a note is the owner's to approve alone.

Prints ``{"count", "notes": [{"path", "title", "age_days", "provenance", "external",
"excerpt"}], "paths", "external", "unreadable": [{"path", "reason"}], "omitted"}``, paths
relative to the hub; ``age_days`` is read from a ``YYYY-MM-DD-`` name (else null). A root that
is not a folder, or a ``--today`` that is not a date, exits 2.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

PROG = "read_inbox.py"
INBOX = "brain/_inbox"
MAX_NOTES = 50
MAX_NOTE_BYTES = 256 * 1024
MAX_FRONT_MATTER_LINES = 64
MAX_EXCERPT_CHARS = 1500
MAX_TITLE_CHARS = 200
MAX_NOTES_BYTES = 96 * 1024
TRUSTED = frozenset({"agent", "agent-from-code", "human"})
LISTED_STATUSES = frozenset({"", "proposed"})
DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


class UnreadableError(Exception):
    """A note the run cannot read; its message is the reason."""


def _split(text: str) -> tuple[dict[str, str], str]:
    """The front matter's ``key: value`` lines and the body after it."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    closing = next((n for n, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if closing is None or closing - 1 > MAX_FRONT_MATTER_LINES:
        raise UnreadableError(f"front matter longer than {MAX_FRONT_MATTER_LINES} lines")
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip()] = value.strip().strip("\"'")
    return fields, "\n".join(lines[closing + 1 :])


def _text(path: Path) -> str:
    if path.is_symlink():
        raise UnreadableError("a link")
    try:
        if path.stat().st_size > MAX_NOTE_BYTES:
            raise UnreadableError("larger than 256 KiB")
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise UnreadableError("not UTF-8") from None
    except OSError as error:
        raise UnreadableError(error.strerror or str(error)) from None


def _age(name: str, today: datetime.date) -> int | None:
    dated = DATED.match(name)
    if dated is None:
        return None
    try:
        return (today - datetime.date.fromisoformat(dated.group(1))).days
    except ValueError:
        return None


def _title(body: str, stem: str) -> str:
    heading = next((line for line in body.split("\n") if line.startswith("# ")), "")
    title = CONTROL.sub("", heading[2:]).strip() or stem
    return title[:MAX_TITLE_CHARS]


def note_of(path: Path, *, shown: str, today: datetime.date) -> dict[str, object] | None:
    """The note as the run lists it; ``None`` when its status says it was handled."""
    fields, body = _split(_text(path))
    if fields.get("status", "") not in LISTED_STATUSES:
        return None
    provenance = fields.get("provenance", "")
    return {
        "path": shown,
        "title": _title(body, path.stem),
        "age_days": _age(path.name, today),
        "provenance": provenance,
        "external": provenance not in TRUSTED,
        "excerpt": CONTROL.sub("", body).strip()[:MAX_EXCERPT_CHARS],
    }


def _size(notes: list[dict[str, object]]) -> int:
    return len(json.dumps(notes, ensure_ascii=False).encode("utf-8"))


def read_inbox(root: Path, *, today: datetime.date) -> dict[str, object]:
    """The listed notes, the unreadable ones and how many wait for a later run."""
    inbox = root / INBOX
    names = sorted(p.name for p in inbox.iterdir()) if inbox.is_dir() else []
    notes: list[dict[str, object]] = []
    unreadable: list[dict[str, str]] = []
    omitted = 0
    for name in names:
        path, shown = inbox / name, f"{INBOX}/{name}"
        if name.startswith(".") or not name.endswith(".md") or path.is_dir():
            continue
        try:
            note = note_of(path, shown=shown, today=today)
        except UnreadableError as error:
            unreadable.append({"path": shown, "reason": str(error)})
            continue
        if note is None:
            continue
        if omitted or len(notes) >= MAX_NOTES or _size([*notes, note]) > MAX_NOTES_BYTES:
            omitted += 1
            continue
        notes.append(note)
    return {
        "count": len(notes),
        "notes": notes,
        "paths": [note["path"] for note in notes],
        "external": [note["path"] for note in notes if note["external"]],
        "unreadable": unreadable,
        "omitted": omitted,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--root", default=".")
    parser.add_argument("--today", default="")
    given = parser.parse_args(argv)
    root = Path(given.root)
    try:
        today = datetime.date.fromisoformat(given.today) if given.today else datetime.date.today()
    except ValueError:
        print(f"{PROG}: --today is not a YYYY-MM-DD date", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"{PROG}: {root} is not a folder", file=sys.stderr)
        return 2
    print(json.dumps(read_inbox(root, today=today)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
