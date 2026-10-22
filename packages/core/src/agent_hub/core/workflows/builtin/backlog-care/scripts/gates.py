# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Walk the planned drafts one gate at a time, and record each decision, as JSON.

``gates.py next --after INDEX``, ``drafts.py plan``'s output on stdin: the item after ``INDEX``
(the first when it is blank, as ``$LOOP_PREV`` is in the first iteration). Prints ``{"index",
"last", "item", "message"}``: one item per iteration, so each issue gets its own approval and
none is batched with another. An index past the last item exits 2.

``gates.py record --item JSON --decision apply|skip --note TEXT --approver TEXT``, the decisions
so far on stdin (blank in the first iteration): appends this item's decision. The owner's note
is recorded beside the draft, never merged into it, cut to ``NOTE_CHARS`` without control
characters. Prints ``{"decisions": [{"id", "decision", "action", "label", "superseded_by",
"draft", "note", "approver"}], "applied"}``, ``applied`` counting the ``apply`` decisions.

Bad stdin or arguments exit 2 with ``gates.py: <reason>`` on stderr.
"""

import argparse
import json
import sys
import unicodedata

NOTE_CHARS = 2000
APPROVER_CHARS = 200
DECISIONS = ("apply", "skip")
MAX_DECISIONS = 50


class BadInputError(Exception):
    """Stdin or an argument cannot be read: the run fails at this node."""


def clean(value: str, limit: int) -> str:
    """Text without control characters but line breaks, cut to ``limit``."""
    return "".join(c for c in value if c == "\n" or unicodedata.category(c) != "Cc")[:limit]


def json_value(given: str, name: str) -> object:
    try:
        return json.loads(given)
    except ValueError as error:
        raise BadInputError(f"{name} is not JSON") from error


def next_item(argv: list[str], stdin: str) -> dict[str, object]:
    parser = argparse.ArgumentParser(prog="gates.py next")
    parser.add_argument("--after", default="")
    after = parser.parse_args(argv).after.strip()
    planned = json_value(stdin, "stdin")
    items = planned.get("items") if isinstance(planned, dict) else None
    if not isinstance(items, list) or not items:
        raise BadInputError("stdin holds no planned item")
    if after and not (after.isascii() and after.isdecimal()):
        raise BadInputError(f"--after is not an index: {after!r}")
    index = int(after) + 1 if after else 0
    if index >= len(items):
        raise BadInputError(f"no item after index {after}: {len(items)} planned")
    item = items[index]
    if not isinstance(item, dict):
        raise BadInputError(f"item {index} is not an object")
    message = item.get("message")
    return {
        "index": index,
        "last": index == len(items) - 1,
        "item": item,
        "message": message if isinstance(message, str) else "",
    }


def record(argv: list[str], stdin: str) -> dict[str, object]:
    parser = argparse.ArgumentParser(prog="gates.py record")
    for name in ("--item", "--decision", "--note", "--approver"):
        parser.add_argument(name, default="")
    given = parser.parse_args(argv)
    item = json_value(given.item, "--item")
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        raise BadInputError("--item is not a planned item")
    if given.decision not in DECISIONS:
        raise BadInputError(f"--decision is not apply or skip: {given.decision!r}")
    before = json_value(stdin, "stdin") if stdin.strip() else []
    if not isinstance(before, list) or len(before) >= MAX_DECISIONS:
        raise BadInputError("stdin is not the decisions so far")
    decision = {
        "id": item["id"],
        "decision": given.decision,
        "action": item.get("action", ""),
        "label": item.get("label", ""),
        "superseded_by": item.get("superseded_by", ""),
        "draft": item.get("draft", {}),
        "note": clean(given.note, NOTE_CHARS),
        "approver": clean(given.approver, APPROVER_CHARS).replace("\n", " "),
    }
    decisions = [*before, decision]
    applied = sum(1 for d in decisions if isinstance(d, dict) and d.get("decision") == "apply")
    return {"decisions": decisions, "applied": applied}


def main(argv: list[str]) -> int:
    verbs = {"next": next_item, "record": record}
    if not argv or argv[0] not in verbs:
        print("gates.py: the first argument is next or record", file=sys.stderr)
        return 2
    try:
        result = verbs[argv[0]](argv[1:], sys.stdin.read())
    except BadInputError as error:
        print(f"gates.py: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
