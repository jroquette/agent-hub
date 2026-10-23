# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Record the mitigation the owner chose at the gate; print it as one JSON object. Nothing is
applied: applying it is the owner's step through /fix (or /change).

``mitigation.py --check <check JSON> --text <owner's text> --approver <name>`` with the
hypotheses reply (``{"hypotheses": [...]}``) on stdin. The choice, in this order: a hypothesis
named in the text (``H<n>``) whose check confirmed it and that proposes a mitigation; else the
owner's own text (``source: owner``); else, when the text is blank, the top-ranked confirmed
hypothesis that proposes one.

Output: ``{id, summary, undo, source: hypothesis|owner, approver}``, ``id`` empty for the
owner's own text. Exit 0; exit 2 on malformed input or when a blank text finds no confirmed
mitigation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

MAX_SUMMARY = 2000
MAX_UNDO = 300
MAX_APPROVER = 200
NAMED = re.compile(r"\bH[1-5]\b")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class BadInputError(Exception):
    """Input this script refuses: exit 2 with its message."""


def clean(value: object, limit: int) -> str:
    return " ".join(CONTROL.sub(" ", str(value)).split())[:limit]


def read(stdin: str, check: str) -> tuple[list[dict[str, Any]], set[str]]:
    try:
        reply, checked = json.loads(stdin), json.loads(check)
    except ValueError as error:
        raise BadInputError(f"not JSON: {error}") from None
    hypotheses = reply.get("hypotheses") if isinstance(reply, dict) else None
    if not isinstance(hypotheses, list) or not all(isinstance(h, dict) for h in hypotheses):
        raise BadInputError('stdin is not {"hypotheses": [objects]}')
    results = checked.get("results") if isinstance(checked, dict) else None
    if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
        raise BadInputError("--check is not the check's results")
    confirmed = {str(r.get("id")) for r in results if r.get("status") == "confirmed"}
    return hypotheses, confirmed


def from_hypothesis(hypothesis: dict[str, Any]) -> dict[str, str]:
    mitigation = hypothesis["mitigation"]
    return {
        "id": str(hypothesis["id"]),
        "summary": clean(mitigation.get("summary", ""), MAX_SUMMARY),
        "undo": clean(mitigation.get("undo", ""), MAX_UNDO),
        "source": "hypothesis",
    }


def choose(hypotheses: list[dict[str, Any]], confirmed: set[str], text: str) -> dict[str, str]:
    """The recorded mitigation, by the order of the module's docstring."""
    offered = {
        str(h.get("id")): h
        for h in hypotheses
        if str(h.get("id")) in confirmed and isinstance(h.get("mitigation"), dict)
    }
    for named in NAMED.findall(text):
        if named in offered:
            return from_hypothesis(offered[named])
    if text.strip():
        return {"id": "", "summary": clean(text, MAX_SUMMARY), "undo": "", "source": "owner"}
    ranked = sorted(
        offered.values(), key=lambda h: h["rank"] if isinstance(h.get("rank"), int) else 99
    )
    if not ranked:
        raise BadInputError("the text is blank and there is no confirmed mitigation to record")
    return from_hypothesis(ranked[0])


OPTIONS = ("--check", "--text", "--approver")


def joined(argv: list[str]) -> list[str]:
    """``argv`` with each option's value attached (``--text=<value>``): the owner's text may
    start with ``-``, which argparse would read as an option."""
    out: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] in OPTIONS and index + 1 < len(argv):
            out.append(f"{argv[index]}={argv[index + 1]}")
            index += 2
        else:
            out.append(argv[index])
            index += 1
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="mitigation.py")
    parser.add_argument("--check", required=True)
    parser.add_argument("--text", default="")
    parser.add_argument("--approver", default="")
    args = parser.parse_args(joined(argv))
    try:
        hypotheses, confirmed = read(sys.stdin.read(), args.check)
        chosen = choose(hypotheses, confirmed, args.text)
    except BadInputError as error:
        print(f"mitigation.py: {error}", file=sys.stderr)
        return 2
    print(json.dumps(chosen | {"approver": clean(args.approver, MAX_APPROVER)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
