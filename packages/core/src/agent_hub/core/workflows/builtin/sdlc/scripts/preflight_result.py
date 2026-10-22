# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Say how one preflight check ended (``preflight-check``), as JSON.

``preflight_result.py --first DRIFT [--recheck DRIFT] [--superseded TEXT]`` prints
``{"status", "drift", "superseded"}``. ``--first`` is the first preflight's drift, ``--recheck``
the re-check's after the owner's decision (blank: none ran). The check ``passed`` when its last
drift is ``none`` or ``local``; it is ``blocked`` when it is still ``plan``: a re-check after the
decision, or a first check given a declined change, that still finds plan drift (A2). ``drift`` is
that last drift; ``TEXT`` is amend-plan's ``moved`` (an approval the plan moved past, A23), passed
on. A drift other than ``none``, ``local`` or ``plan`` (``--recheck`` may be blank) exits 2.
"""

import argparse
import json
import sys

DRIFTS = ("none", "local", "plan")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="preflight_result.py")
    parser.add_argument("--first", default="")
    parser.add_argument("--recheck", default="")
    parser.add_argument("--superseded", default="")
    given = parser.parse_args(argv)
    if given.first not in DRIFTS or given.recheck not in ("", *DRIFTS):
        print("preflight_result.py: a drift is none, local or plan", file=sys.stderr)
        return 2
    drift = given.recheck or given.first
    status = "blocked" if drift == "plan" else "passed"
    print(json.dumps({"status": status, "drift": drift, "superseded": given.superseded}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
