# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Write the owner's inbox decisions into the run's hub worktree and commit them, as JSON.

``apply.py --worktree PATH --base SHA [--today YYYY-MM-DD] [--unreadable JSON]`` reads the
decisions ``groups.py record`` kept (``[{"group", "decision", "note", "approver"}]``) on stdin
and, in the worktree ``hub_branch.py`` made:

- ``keep`` changes nothing; ``drop`` (or ``apply`` of a ``drop``) deletes the group's notes;
- ``apply`` of a ``promote`` writes the group's text (else the notes' bodies) into its target
  under ``brain/learnings/`` (a ``.md`` file: created with ``status: accepted`` and
  ``last_verified``, or appended to as a ``## <title>`` section; a folder ``…/``: a new file named
  after the first note without its date), then deletes the notes. A target outside
  ``brain/learnings/`` (``brain/decisions/`` is never edited), or an external note in a group of
  several, is skipped;
- ``apply`` of a ``route`` or ``check`` sets the note's ``status`` and ``routed_to`` in place: a
  follow-up for the owner (a hub PR cannot change a repo or the tracker; ADR 0030).

A note the base commit lacks is skipped ("push it first"), as is a path that is not an inbox
note. The changes are committed as the checkout's git identity, hooks off, and the commit must
change only ``brain/`` paths. Prints ``{"changes", "deleted", "written", "edited", "skipped":
[{"path", "reason"}], "summary"}``; ``summary`` (at most 8,000 characters) is the PR body's:
each decision with its approver and note, the follow-ups, the skipped and unreadable notes.
Input that is not a list of decisions exits 2; a git failure, or a commit that leaves
``brain/``, exits 1.
"""

import argparse
import datetime
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

PROG = "apply.py"
INBOX = "brain/_inbox/"
LEARNINGS = "brain/learnings/"
TRUSTED = frozenset({"agent", "agent-from-code", "human"})
MAX_SUMMARY_CHARS = 8000
COMMIT_SUBJECT = "docs(brain): weekly inbox review"
GIT_TIMEOUT = 120
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}-")
NOT_NOTE = "not an inbox note"
ABSENT = "not in the base commit: push it to the default branch first"
OUTSIDE = "a promote target outside brain/learnings/"
NOT_ALONE = "an external note is promoted only alone, by its own approval"


class Change(NamedTuple):
    kind: str  # delete, write or edit
    path: str
    text: str


class Planned(NamedTuple):
    changes: list[Change]
    skipped: list[dict[str, str]]


class BadInputError(Exception):
    """Decisions that are not a list of objects: exit 2."""


class GitFailedError(Exception):
    """A git command failed, or the commit left brain/: exit 1."""


def _split(text: str) -> tuple[list[str], str]:
    """The front matter's lines (``[]`` when none) and the body."""
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        closing = next((n for n, line in enumerate(lines[1:], 1) if line.strip() == "---"), 0)
        if closing:
            return lines[1:closing], "\n".join(lines[closing + 1 :])
    return [], text


def _field(head: list[str], key: str) -> str:
    found = (line.partition(":")[2] for line in head if line.partition(":")[0].strip() == key)
    return next(found, "").strip().strip("\"'")


def _with_fields(head: list[str], fields: dict[str, str]) -> list[str]:
    kept = [line for line in head if line.partition(":")[0].strip() not in fields]
    return kept + [f"{key}: {value}" for key, value in fields.items()]


def _joined(head: list[str], body: str) -> str:
    return "\n".join(["---", *head, "---", body.lstrip("\n")])


def _title(body: str, fallback: str) -> str:
    heading = next((line for line in body.split("\n") if line.startswith("# ")), "")
    return heading[2:].strip() or fallback


class _Tree:
    """The worktree as the planned changes leave it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state: dict[str, str | None] = {}

    def read(self, path: str) -> str | None:
        if path not in self.state:
            file = self.root / path
            is_file = file.is_file() and not file.is_symlink()
            self.state[path] = file.read_text(encoding="utf-8") if is_file else None
        return self.state[path]

    def put(self, path: str, text: str | None) -> None:
        self.state[path] = text


def _is_note(path: str) -> bool:
    name = path.removeprefix(INBOX)
    return path.startswith(INBOX) and "/" not in name and name.endswith(".md") and ".." not in name


def is_learning(target: str) -> bool:
    if not target.startswith(LEARNINGS) or "\\" in target or ".." in target.split("/"):
        return False
    return posixpath.normpath(target).startswith(LEARNINGS)


def _notes(group: dict[str, object], tree: _Tree, skipped: list[dict[str, str]]) -> list[str]:
    """The group's notes this run can change; the others go to ``skipped``."""
    found = group.get("notes")
    kept: list[str] = []
    for note in found if isinstance(found, list) else []:
        path = str(note)
        if not _is_note(path):
            skipped.append({"path": path, "reason": NOT_NOTE})
        elif tree.read(path) is None:
            skipped.append({"path": path, "reason": ABSENT})
        else:
            kept.append(path)
    return kept


def _learning_path(target: str, first: str) -> str:
    if target.endswith("/"):
        return target + DATED.sub("", first.rsplit("/", 1)[-1])
    return target


def _promoted(group: dict[str, object], notes: list[str], tree: _Tree, *, today: str) -> Change:
    parts = [_split(tree.read(note) or "") for note in notes]
    first_title = _title(parts[0][1], Path(notes[0]).stem)
    text = str(group.get("text") or "").strip()
    text = text or "\n\n".join(body.strip() for _, body in parts)
    path = _learning_path(str(group.get("target")), notes[0])
    existing = tree.read(path)
    if existing is not None:
        head, body = _split(existing)
        if head:
            existing = _joined(_with_fields(head, {"last_verified": today}), body)
        updated = existing.rstrip("\n") + f"\n\n## {first_title}\n\n{text}\n"
    else:
        provenances = {_field(head, "provenance") for head, _ in parts}
        fields = {
            "type": "learning",
            "status": "accepted",
            "last_verified": today,
            "provenance": provenances.pop() if len(provenances) == 1 else "agent",
            "sources": "[" + ", ".join(notes) + "]",
        }
        updated = _joined([f"{k}: {v}" for k, v in fields.items()], f"# {first_title}\n\n{text}\n")
    tree.put(path, updated)
    return Change("write", path, updated)


def _deleted(notes: list[str], tree: _Tree) -> list[Change]:
    for note in notes:
        tree.put(note, None)
    return [Change("delete", note, "") for note in notes]


def _routed(group: dict[str, object], notes: list[str], tree: _Tree) -> list[Change]:
    changes = []
    for note in notes:
        head, body = _split(tree.read(note) or "")
        fields = {"status": str(group.get("action")), "routed_to": str(group.get("target"))}
        text = _joined(_with_fields(head, fields), body)
        tree.put(note, text)
        changes.append(Change("edit", note, text))
    return changes


def _promote(
    group: dict[str, object], notes: list[str], tree: _Tree, *, today: str
) -> tuple[list[Change], list[dict[str, str]]]:
    target = str(group.get("target"))
    if not is_learning(target):
        return [], [{"path": target, "reason": OUTSIDE}]
    outside = [
        n for n in notes if _field(_split(tree.read(n) or "")[0], "provenance") not in TRUSTED
    ]
    if outside and len(notes) > 1:
        return [], [{"path": note, "reason": NOT_ALONE} for note in outside]
    return [_promoted(group, notes, tree, today=today), *_deleted(notes, tree)], []


def planned_changes(
    decisions: list[dict[str, object]], *, root: Path, today: datetime.date
) -> Planned:
    """The files the decisions change, in order, and what they skip."""
    tree = _Tree(root)
    changes: list[Change] = []
    skipped: list[dict[str, str]] = []
    for decision in decisions:
        group = decision.get("group")
        if decision.get("decision") not in ("apply", "drop") or not isinstance(group, dict):
            continue
        notes = _notes(group, tree, skipped)
        action = group.get("action") if decision.get("decision") == "apply" else "drop"
        if not notes:
            continue
        if action == "promote":
            found, missed = _promote(group, notes, tree, today=today.isoformat())
            changes += found
            skipped += missed
        elif action in ("route", "check"):
            changes += _routed(group, notes, tree)
        else:
            changes += _deleted(notes, tree)
    return Planned(changes=changes, skipped=skipped)


def write_changes(root: Path, changes: list[Change]) -> None:
    """Make the planned changes in the worktree."""
    for change in changes:
        file = root / change.path
        if change.kind == "delete":
            file.unlink(missing_ok=True)
        else:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(change.text, encoding="utf-8")


def _decision_line(decision: dict[str, object]) -> str:
    group = decision.get("group")
    group = group if isinstance(group, dict) else {}
    notes = group.get("notes")
    shown = ", ".join(str(n) for n in notes) if isinstance(notes, list) else ""
    line = (
        f"- Group {group.get('id')} ({group.get('action')} -> {group.get('target')}):"
        f" {decision.get('decision')} by {decision.get('approver') or 'the owner'}. Notes: {shown}."
    )
    note = " ".join(str(decision.get("note") or "").split())
    return f"{line} Owner's note: {note}" if note else line


def _listed(items: list[dict[str, str]]) -> list[str]:
    return [f"- {item['path']}: {item['reason']}" for item in items]


def summary_of(
    decisions: list[dict[str, object]], planned: Planned, *, unreadable: list[dict[str, str]]
) -> str:
    """The PR body's summary: the decisions, the follow-ups, what was skipped or unreadable."""
    lines = ["Weekly inbox review (brain-care inbox run).", "", "Decisions:"]
    lines += [_decision_line(decision) for decision in decisions]
    followups = []
    for change in planned.changes:
        if change.kind == "edit":
            head = _split(change.text)[0]
            routed = f"{_field(head, 'status')} -> {_field(head, 'routed_to')}"
            followups.append(f"- {change.path}: {routed}")
    sections = (
        ("Follow-ups for the owner (not done by this PR):", followups),
        ("Skipped:", _listed(planned.skipped)),
        ("Unreadable notes (left in the inbox):", _listed(unreadable)),
    )
    for heading, items in sections:
        if items:
            lines += ["", heading, *items]
    return "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _git(root: Path, *args: str) -> str:
    command = ["git", "-c", "core.hooksPath=/dev/null", *args]
    try:
        done = subprocess.run(  # noqa: S603 - git from PATH, arguments the script built
            command, cwd=root, capture_output=True, text=True, check=False, timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitFailedError(f"git {args[0]}: {error}") from None
    if done.returncode != 0:
        raise GitFailedError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def commit(root: Path, *, base: str) -> None:
    """Commit the brain changes; refuse a branch whose diff leaves ``brain/``."""
    _git(root, "add", "-A", "--", "brain")
    _git(root, "commit", "-q", "-m", COMMIT_SUBJECT)
    changed = _git(root, "diff", "--name-only", f"{base}..HEAD").splitlines()
    outside = [path for path in changed if not path.startswith("brain/")]
    if outside:
        raise GitFailedError(f"the branch changes paths outside brain/: {', '.join(outside)}")


def _decisions(text: str) -> list[dict[str, object]]:
    try:
        found = json.loads(text) if text.strip() else []
    except ValueError:
        raise BadInputError("stdin is not JSON") from None
    if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
        raise BadInputError("stdin is not a list of decisions")
    return found


def _unreadable(text: str) -> list[dict[str, str]]:
    try:
        found = json.loads(text) if text.strip() else []
    except ValueError:
        raise BadInputError("--unreadable is not JSON") from None
    if not isinstance(found, list):
        raise BadInputError("--unreadable is not a list")
    items = [item for item in found if isinstance(item, dict)]
    return [{"path": str(i.get("path")), "reason": str(i.get("reason"))} for i in items]


def apply(given: argparse.Namespace, stdin: str) -> dict[str, object]:
    decisions, unreadable = _decisions(stdin), _unreadable(given.unreadable)
    try:
        today = datetime.date.fromisoformat(given.today) if given.today else datetime.date.today()
    except ValueError:
        raise BadInputError("--today is not a YYYY-MM-DD date") from None
    root = Path(given.worktree)
    planned = planned_changes(decisions, root=root, today=today)
    if planned.changes:
        write_changes(root, planned.changes)
        commit(root, base=given.base)

    def paths(kind: str) -> list[str]:
        return list(dict.fromkeys(c.path for c in planned.changes if c.kind == kind))

    return {
        "changes": len(planned.changes),
        "deleted": paths("delete"),
        "written": paths("write"),
        "edited": paths("edit"),
        "skipped": planned.skipped,
        "summary": summary_of(decisions, planned, unreadable=unreadable),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--today", default="")
    parser.add_argument("--unreadable", default="")
    given = parser.parse_args(argv)
    try:
        found = apply(given, sys.stdin.read())
    except BadInputError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    except (GitFailedError, OSError) as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
