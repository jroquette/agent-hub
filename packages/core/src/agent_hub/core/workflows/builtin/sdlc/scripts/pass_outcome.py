# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Say how one ``ticket-pass`` ended, from its review rounds' output, as JSON.

``pass_outcome.py --rounds JSON --worktree JSON`` prints ``{"status", "question", "discovery",
"verdict", "path", "base", "target"}``. Blank rounds (they did not run: no preflight passed, as a
re-check after the owner's decision, or of a declined change, still found plan drift) is
``blocked``. Otherwise the last round's session ``blocked`` (its question), its ``discovery``
(the run starts the next pass with it) or ``done`` with the review's verdict. ``path``, ``base``
and ``target`` are the pass's worktree's (``""``, ``""`` and null when it made none). Text that
is not JSON exits 2.
"""

import argparse
import json
import sys

STILL_PLAN = (
    "plan drift remains after the owner's decision on the plan change: "
    "the next /implement opens a new change request"
)


def loaded(text: str, what: str) -> dict[str, object]:
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise ValueError(f"pass_outcome.py: {what} is not a JSON object")
    return value


def part(rounds: dict[str, object], node: str, key: str) -> str:
    output = rounds.get(node)
    value = output.get(key) if isinstance(output, dict) else None
    return value if isinstance(value, str) else ""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pass_outcome.py")
    parser.add_argument("--rounds", default="")
    parser.add_argument("--worktree", default="")
    given = parser.parse_args(argv)
    try:
        rounds, worktree = loaded(given.rounds, "--rounds"), loaded(given.worktree, "--worktree")
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    outcome = {
        "status": "done",
        "question": "",
        "discovery": "",
        "verdict": "",
        "path": worktree.get("path", ""),
        "base": worktree.get("base", ""),
        "target": worktree.get("target"),
    }
    if not rounds:
        outcome |= {"status": "blocked", "question": STILL_PLAN}
    elif part(rounds, "verdict", "status") == "blocked":
        outcome |= {"status": "blocked", "question": part(rounds, "verdict", "question")}
    elif discovery := part(rounds, "verdict", "discovery"):
        outcome |= {"status": "discovery", "discovery": discovery}
    else:
        outcome["verdict"] = part(rounds, "review", "verdict")
    print(json.dumps(outcome))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
