# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Say how one ``ticket-pass`` ended, from its review rounds' output, as JSON.

``pass_outcome.py --rounds JSON [--request N]...`` prints ``{"status", "question", "discovery",
"verdict"}``. Blank rounds (they did not run: the re-preflight after the owner's decision still
found plan drift, or a declined change was re-checked and still was) is ``blocked``, naming the
first ``--request`` given; otherwise the last round's session ``blocked`` (its question), a
``discovery`` (its text: the run starts the next pass with it) or ``done`` with the review's
verdict. Text that is not JSON exits 2.
"""

import argparse
import json
import sys

STILL_PLAN = (
    "plan drift remains after the owner's decision on change request {n}: "
    "the next /implement opens a new change request"
)


def part(rounds: dict[str, object], node: str, key: str) -> str:
    output = rounds.get(node)
    value = output.get(key) if isinstance(output, dict) else None
    return value if isinstance(value, str) else ""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pass_outcome.py")
    parser.add_argument("--rounds", default="")
    parser.add_argument("--request", action="append", default=[])
    given = parser.parse_args(argv)
    outcome = {"status": "done", "question": "", "discovery": "", "verdict": ""}
    if not given.rounds.strip():
        n = next((n for n in given.request if n.strip()), "?")
        outcome |= {"status": "blocked", "question": STILL_PLAN.format(n=n)}
        print(json.dumps(outcome))
        return 0
    try:
        rounds = json.loads(given.rounds)
    except ValueError:
        rounds = None
    if not isinstance(rounds, dict):
        print("pass_outcome.py: --rounds is not a JSON object", file=sys.stderr)
        return 2
    if part(rounds, "verdict", "status") == "blocked":
        outcome |= {"status": "blocked", "question": part(rounds, "verdict", "question")}
    elif discovery := part(rounds, "discovery", "discovery"):
        outcome |= {"status": "discovery", "discovery": discovery}
    else:
        outcome["verdict"] = part(rounds, "review", "verdict")
    print(json.dumps(outcome))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
