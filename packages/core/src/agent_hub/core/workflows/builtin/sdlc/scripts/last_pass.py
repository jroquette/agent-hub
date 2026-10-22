# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Say how the ``implement`` run's passes ended, from each pass's outcome, as JSON.

``implement.yaml`` includes ``ticket-pass`` up to three times; a pass runs only when the one
before it ended with a discovery or a superseded approval. ``last_pass.py [--superseded TEXT]
--pass JSON...`` takes each pass's ``pass_outcome.py`` output in order (blank: it did not run)
and prints ``{"status", "question", "verdict", "pass", "path", "base", "target", "superseded"}``
for the last one that ran: ``status`` ``blocked`` or ``done`` (what ``hub step report
--status`` reads), its question, review verdict and number, and its worktree (the eval, the
commits and the PR read it). ``superseded`` joins every approval the plan moved past (A23): the
pending decision's ``TEXT`` and each pass's, for the report. A last pass given that asks for
another (a discovery or a superseded approval: two loops back at most, D-3) is ``blocked``,
naming it. Text that is not JSON, or no pass, exits 2.
"""

import argparse
import json
import sys

TOO_MANY = "pass {n}, the last one, asks for another: {text}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="last_pass.py")
    parser.add_argument("--pass", dest="passes", action="append", default=[])
    parser.add_argument("--superseded", default="")
    given = parser.parse_args(argv)
    ran = [(n, text) for n, text in enumerate(given.passes, start=1) if text.strip()]
    if not ran:
        print("last_pass.py: no pass ran", file=sys.stderr)
        return 2
    passes: list[dict[str, object]] = []
    for _, text in ran:
        try:
            found = json.loads(text)
        except ValueError:
            found = None
        if not isinstance(found, dict):
            print("last_pass.py: a --pass is not a JSON object", file=sys.stderr)
            return 2
        passes.append(found)
    n, last = ran[-1][0], passes[-1]
    status, question = last.get("status"), last.get("question") or ""
    if last.get("next_input"):
        status, question = "blocked", TOO_MANY.format(n=n, text=last.get("next_text") or "")
    texts = [given.superseded, *(str(found.get("superseded") or "") for found in passes)]
    result = {
        "status": "blocked" if status == "blocked" else "done",
        "question": question,
        "verdict": last.get("verdict") or "",
        "pass": n,
        "path": last.get("path") or "",
        "base": last.get("base") or "",
        "target": last.get("target"),
        "superseded": "; ".join(text for text in texts if text),
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
