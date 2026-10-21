# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Say how the ``implement`` run's passes ended, from each pass's outcome, as JSON.

``implement.yaml`` includes ``ticket-pass`` up to three times; a pass runs only when the one
before it ended with a discovery. ``last_pass.py --pass JSON...`` takes each pass's
``pass_outcome.py`` output in order (blank: it did not run) and prints ``{"status",
"question", "verdict", "pass"}`` for the last one that ran: ``status`` ``blocked`` or ``done``
(what ``hub step report --status`` reads), its question and review verdict, and its number. A
discovery in the last pass given is the one too many (two loops back at most, D-3): ``blocked``,
naming it. Text that is not JSON, or no pass, exits 2.
"""

import argparse
import json
import sys

TOO_MANY = "a discovery in pass {n}, the last one: {text}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="last_pass.py")
    parser.add_argument("--pass", dest="passes", action="append", default=[])
    given = parser.parse_args(argv)
    ran = [(n, text) for n, text in enumerate(given.passes, start=1) if text.strip()]
    if not ran:
        print("last_pass.py: no pass ran", file=sys.stderr)
        return 2
    n, text = ran[-1]
    try:
        last = json.loads(text)
    except ValueError:
        last = None
    if not isinstance(last, dict):
        print("last_pass.py: a --pass is not a JSON object", file=sys.stderr)
        return 2
    status, question = last.get("status"), last.get("question") or ""
    if status == "discovery":
        status, question = "blocked", TOO_MANY.format(n=n, text=last.get("discovery") or "")
    result = {
        "status": "blocked" if status == "blocked" else "done",
        "question": question,
        "verdict": last.get("verdict") or "",
        "pass": n,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
