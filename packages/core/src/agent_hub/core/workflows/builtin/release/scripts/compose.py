# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Compose the release notes (the tag message and the release PR's body), as JSON.

``compose.py --version X.Y.Z --last-tag vX.Y.Z --sync <text>`` reads the notes agent's sections
on stdin, one JSON object of strings: ``features``, ``fixes``, ``doctor``, ``migration``,
``summary``. ``--sync`` is ``pin.py list``'s ``text``, one ``<verb> <path>`` line per file
(``none`` when nothing changes), copied verbatim: the list is computed, never written by the
agent. The notes hold a title line, the summary, then five sections: Features / Fixes / What
``hub sync`` rewrites in every hub / Doctor rules added or changed / Migration steps (an empty
one says ``none``).

The notes fit ``MAX_NOTES`` characters, under GitHub's 65,535-character dispatch input: over
it, the sync list becomes a count per top folder (the hub PR keeps the full list); still over,
the text is cut with ``…``. Prints ``{"notes", "chars", "trimmed"}``. Notes that are not that
object exit 2.
"""

import argparse
import json
import sys

PROG = "compose.py"
MAX_NOTES = 60000
SECTIONS = ("features", "fixes", "doctor", "migration", "summary")
SYNC_HEADING = "What `hub sync` rewrites in every hub"


def counts(sync: str) -> str:
    """The sync list as a count of files per top folder, in first-seen order."""
    per: dict[str, int] = {}
    for line in sync.splitlines():
        path = line.split(" ", 1)[-1].strip()
        if not path or line.startswith("and "):
            continue
        top = path.split("/", 1)[0] + ("/" if "/" in path else "")
        per[top] = per.get(top, 0) + 1
    lines = [f"- {top}: {n} file{'' if n == 1 else 's'}" for top, n in per.items()]
    return "\n".join([*lines, "", "(a count per folder; the full list in the hub PR)"])


def listed(sync: str) -> str:
    lines = [line.strip() for line in sync.splitlines() if line.strip()]
    if not lines or lines == ["none"]:
        return "none"
    return "\n".join(f"- {line}" for line in lines)


def notes_of(sections: dict[str, str], *, version: str, last_tag: str, sync: str) -> str:
    def part(heading: str, text: str) -> str:
        return f"## {heading}\n\n{text.strip() or 'none'}\n"

    summary = sections["summary"].strip()
    head = f"v{version} (since {last_tag})\n\n" + (f"{summary}\n\n" if summary else "")
    return head + "\n".join(
        [
            part("Features", sections["features"]),
            part("Fixes", sections["fixes"]),
            part(SYNC_HEADING, sync),
            part("Doctor rules added or changed", sections["doctor"]),
            part("Migration steps", sections["migration"]),
        ]
    )


def composed(
    sections: dict[str, str], *, version: str, last_tag: str, sync: str
) -> dict[str, object]:
    notes = notes_of(sections, version=version, last_tag=last_tag, sync=listed(sync))
    trimmed = len(notes) > MAX_NOTES
    if trimmed and listed(sync) != "none":
        notes = notes_of(sections, version=version, last_tag=last_tag, sync=counts(sync))
    if len(notes) > MAX_NOTES:
        notes = notes[: MAX_NOTES - 1] + "…"
    return {"notes": notes, "chars": len(notes), "trimmed": trimmed}


def read_sections(text: str) -> dict[str, str]:
    try:
        value = json.loads(text)
    except ValueError as error:
        raise ValueError(f"the notes are not JSON: {error}") from None
    if not isinstance(value, dict):
        raise ValueError("the notes are not a JSON object")
    found = {name: value.get(name, "") for name in SECTIONS}
    if not all(isinstance(text, str) for text in found.values()):
        raise ValueError(f"each of {', '.join(SECTIONS)} must be text")
    return found


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
    parser.add_argument("--version", required=True)
    parser.add_argument("--last-tag", required=True)
    parser.add_argument("--sync", required=True)
    given = parser.parse_args(joined(argv, frozenset({"--version", "--last-tag", "--sync"})))
    try:
        sections = read_sections(sys.stdin.read())
    except ValueError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    found = composed(sections, version=given.version, last_tag=given.last_tag, sync=given.sync)
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
