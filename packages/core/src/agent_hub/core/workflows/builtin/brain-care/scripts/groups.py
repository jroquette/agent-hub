# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The groups of inbox notes the owner decides one by one in a brain-care ``inbox`` run, as JSON.

Three subcommands, each printing one JSON object:

- ``groups.py plan --paths JSON --external JSON`` reads the ``group`` agent's reply on stdin
  (``{"groups": [{"notes", "action", "target", "reason", "text"}]}``) and checks it against what
  ``read_inbox.py`` read: a path not read, or already in an earlier group, is ``ignored``; a
  ``promote`` whose target is not under ``brain/learnings/`` is ``ignored`` whole; an external
  note is always split into a group of its own, whatever the agent proposed, so it gets its own
  approval. Prints ``{"count", "groups": [{"id", "notes", "external", "action", "target",
  "reason", "text"}], "ignored": [{"notes", "reason"}], "unproposed": [paths no group holds]}``.
- ``groups.py next --after INDEX`` reads ``plan``'s output on stdin and prints the group after
  ``INDEX`` (the first when blank) for the loop's gate: ``{"index", "last", "group",
  "message"}``. An index past the last group exits 2.
- ``groups.py record --group JSON --decision apply|drop|keep --note TEXT --approver NAME`` reads
  the decisions so far on stdin (blank at first) and prints them with this one added:
  ``{"decisions": [{"group", "decision", "note", "approver"}], "acted"}`` (``acted`` counts the
  decisions that change the brain: all but ``keep``). The note is cut at 2,000 characters.

Input that is not the JSON expected, or an unknown decision, exits 2.
"""

import argparse
import json
import posixpath
import sys

PROG = "groups.py"
LEARNINGS = "brain/learnings/"
DECISIONS = ("apply", "drop", "keep")
MAX_NOTE_CHARS = 2000
NOT_READ = "not read by this run"
TAKEN = "already in an earlier group"
OUTSIDE = "a promote target outside brain/learnings/"
SPLIT = " (an external note, split from its group: it needs its own approval)"
EXTERNAL_WARNING = (
    "This note is external (its provenance is not agent or human): it needs your explicit"
    " approval. Apply it only once you have checked its source."
)
CHOICES = (
    "Decide: apply (as proposed), drop (delete the notes) or keep (leave them in the inbox);"
    " a note goes in the PR body beside your decision."
)


class BadInputError(Exception):
    """Input that is not what the subcommand reads: exit 2."""


def _json(text: str, what: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        raise BadInputError(f"{what} is not JSON") from None


def _strings(value: object, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BadInputError(f"{what} is not a list of paths")
    return list(value)


def _objects(value: object, what: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise BadInputError(f"{what} is not a list of objects")
    return list(value)


def is_learning(target: str) -> bool:
    """Whether a ``promote`` target stays under ``brain/learnings/``."""
    if not target.startswith(LEARNINGS) or "\\" in target:
        return False
    return posixpath.normpath(target).startswith(LEARNINGS) and ".." not in target.split("/")


def proposed_notes(proposed: dict[str, object]) -> list[str]:
    notes = proposed.get("notes")
    return [note for note in notes if isinstance(note, str)] if isinstance(notes, list) else []


def _group(proposed: dict[str, object], notes: list[str], *, split: bool) -> dict[str, object]:
    """A group as the gate shows it; ``split``: an external note taken out of its group, which
    keeps the action but not the merged text (the owner reads the note itself)."""
    reason = str(proposed.get("reason", ""))
    return {
        "notes": notes,
        "external": split,
        "action": str(proposed.get("action", "")),
        "target": str(proposed.get("target", "")),
        "reason": reason + SPLIT if split else reason,
        "text": "" if split else str(proposed.get("text", "")),
    }


def _checked(
    proposed: dict[str, object], *, read: list[str], taken: set[str]
) -> tuple[list[str], list[dict[str, object]]]:
    """The proposal's notes this run can decide, and the ones it ignores, with why."""
    notes = proposed_notes(proposed)
    unknown = [note for note in notes if note not in read]
    again = [note for note in notes if note in read and note in taken]
    kept = [note for note in notes if note in read and note not in taken]
    ignored: list[dict[str, object]] = [
        {"notes": found, "reason": reason}
        for found, reason in ((unknown, NOT_READ), (again, TAKEN))
        if found
    ]
    if (
        kept
        and proposed.get("action") == "promote"
        and not is_learning(str(proposed.get("target")))
    ):
        return [], [*ignored, {"notes": kept, "reason": OUTSIDE}]
    return kept, ignored


def plan(
    proposals: list[dict[str, object]], *, read: list[str], external: set[str]
) -> dict[str, object]:
    """The agent's groups checked against what was read; each external note alone."""
    groups: list[dict[str, object]] = []
    ignored: list[dict[str, object]] = []
    taken: set[str] = set()
    for proposed in proposals:
        kept, skipped = _checked(proposed, read=read, taken=taken)
        ignored += skipped
        taken.update(kept)
        inside = [note for note in kept if note not in external]
        alone = [note for note in kept if note in external]
        if inside:
            groups.append(_group(proposed, inside, split=False))
        for note in alone:
            group = _group(proposed, [note], split=len(kept) > 1)
            groups.append(group | {"external": True})
    numbered = [{"id": n, **group} for n, group in enumerate(groups, start=1)]
    return {
        "count": len(numbered),
        "groups": numbered,
        "ignored": ignored,
        "unproposed": [path for path in read if path not in taken],
    }


def message(group: dict[str, object], *, count: int) -> str:
    """The gate's text for one group."""
    notes = group.get("notes")
    shown = ", ".join(str(note) for note in notes) if isinstance(notes, list) else ""
    lines = [
        f"Group {group.get('id')} of {count}: {group.get('action')} -> {group.get('target')}.",
        f"Notes: {shown}.",
        f"Reason: {group.get('reason')}",
    ]
    if group.get("text"):
        lines.append(f"Proposed text: {group.get('text')}")
    if group.get("external"):
        lines.append(EXTERNAL_WARNING)
    lines.append(CHOICES)
    return "\n".join(lines)


def next_group(planned: object, *, after: str) -> dict[str, object]:
    groups = _objects(planned.get("groups") if isinstance(planned, dict) else None, "the plan")
    try:
        index = int(after) + 1 if after.strip() else 0
    except ValueError:
        raise BadInputError("--after is not an index") from None
    if not 0 <= index < len(groups):
        raise BadInputError(f"no group after {after or 'the start'}")
    group = groups[index]
    return {
        "index": index,
        "last": index == len(groups) - 1,
        "group": group,
        "message": message(group, count=len(groups)),
    }


def record(
    previous: str, *, group: str, decision: str, note: str, approver: str
) -> dict[str, object]:
    decisions = _objects(_json(previous, "stdin") if previous.strip() else [], "stdin")
    found = _json(group, "--group")
    if not isinstance(found, dict):
        raise BadInputError("--group is not a JSON object")
    if decision not in DECISIONS:
        raise BadInputError(f"--decision is not one of {', '.join(DECISIONS)}")
    decisions.append(
        {"group": found, "decision": decision, "note": note[:MAX_NOTE_CHARS], "approver": approver}
    )
    acted = sum(1 for item in decisions if item.get("decision") != "keep")
    return {"decisions": decisions, "acted": acted}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG)
    commands = parser.add_subparsers(dest="command", required=True)
    planning = commands.add_parser("plan")
    planning.add_argument("--paths", required=True)
    planning.add_argument("--external", required=True)
    nexts = commands.add_parser("next")
    nexts.add_argument("--after", default="")
    recording = commands.add_parser("record")
    for name in ("--group", "--decision", "--note", "--approver"):
        recording.add_argument(name, required=True)
    return parser


def run(given: argparse.Namespace, stdin: str) -> dict[str, object]:
    if given.command == "plan":
        read = _strings(_json(given.paths, "--paths"), "--paths")
        external = set(_strings(_json(given.external, "--external"), "--external"))
        reply = _json(stdin, "stdin")
        proposals = _objects(reply.get("groups") if isinstance(reply, dict) else None, "stdin")
        return plan(proposals, read=read, external=external)
    if given.command == "next":
        return next_group(_json(stdin, "stdin"), after=given.after)
    return record(
        stdin,
        group=given.group,
        decision=given.decision,
        note=given.note,
        approver=given.approver,
    )


def _joined(argv: list[str]) -> list[str]:
    """``record``'s options as ``--name=value``: a value is the next argument whatever it holds
    (the owner's note may start with ``-``), as the workflow passes each reference whole."""
    if argv[:1] != ["record"]:
        return argv
    rest = argv[1:]
    pairs = zip(rest[::2], rest[1::2], strict=False)
    return ["record", *(f"{name}={value}" for name, value in pairs), *rest[len(rest) // 2 * 2 :]]


def main(argv: list[str]) -> int:
    given = _parser().parse_args(_joined(argv))
    try:
        found = run(given, sys.stdin.read())
    except BadInputError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
