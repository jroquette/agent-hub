# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Turn the preflight agent's findings into one ``agent-hub/preflight/1`` run, as JSON.

``preflight_run.py --agent JSON --input KIND [--text TEXT] [--request N]...`` prints the run
``hub step preflight --run`` appends: the agent's ``plan_version``, ``commit``,
``blockers_read``, ``drift`` and ``local_notes``; ``ran_at`` now (UTC); ``run_id`` from
``AGENT_HUB_RUN_ID`` (the engine gives it to the run's scripts); ``input`` from ``KIND``
(``none``, ``discovery``, ``declined_change``; a gate's ``approve`` reads ``none`` and its
``decline`` ``declined_change``) with ``TEXT`` as one line of at most 1000 characters (null for
``none``); and, for ``plan`` drift, ``change_request``: the first ``--request`` given that is a
number (the request this run opened, or the decided one it re-checked), else null. The writer
checks the run with core's model. A bad argument or no run id exits 2.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime

INPUTS = {
    "none": "none",
    "discovery": "discovery",
    "declined_change": "declined_change",
    "approve": "none",
    "decline": "declined_change",
}
MAX_TEXT = 1000
AGENT_KEYS = ("plan_version", "commit", "blockers_read", "drift", "local_notes")


def one_line(text: str) -> str:
    kept = "".join(c for c in text if c.isprintable() or c.isspace())
    return " ".join(kept.split())[:MAX_TEXT]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="preflight_run.py")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--input", required=True, choices=sorted(INPUTS))
    parser.add_argument("--text", default="")
    parser.add_argument("--request", action="append", default=[])
    given = parser.parse_args(argv)
    run_id = os.environ.get("AGENT_HUB_RUN_ID", "")
    try:
        agent = json.loads(given.agent)
    except ValueError:
        agent = None
    if not isinstance(agent, dict) or not run_id:
        print("preflight_run.py: --agent is not a JSON object, or no run id", file=sys.stderr)
        return 2
    kind = INPUTS[given.input]
    numbers = [int(n) for n in given.request if n.isascii() and n.isdecimal()]
    drift = agent.get("drift")
    run = {key: agent.get(key) for key in AGENT_KEYS}
    run |= {
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "input": kind,
        "input_text": None if kind == "none" else one_line(given.text),
        "change_request": numbers[0] if drift == "plan" and numbers else None,
        "run_id": run_id,
    }
    print(json.dumps(run))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
