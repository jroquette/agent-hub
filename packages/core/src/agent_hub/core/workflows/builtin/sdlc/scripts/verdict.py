# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Join the review lenses' verdicts into one and print it as JSON.

``verdict.py --spec <PASS|FAIL> --quality <PASS|FAIL>`` prints
``{"verdict", "lenses": {"spec", "quality"}}``: ``PASS`` only when both lenses pass. Each lens's
whole review stays its own node's output in the run's record; only the verdicts travel here,
so no argument grows with the findings. Any other value exits 2.
"""

import argparse
import json
import sys

VERDICTS = ("PASS", "FAIL")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="verdict.py")
    parser.add_argument("--spec", required=True, choices=VERDICTS)
    parser.add_argument("--quality", required=True, choices=VERDICTS)
    given = parser.parse_args(argv)
    lenses = {"spec": given.spec, "quality": given.quality}
    verdict = "PASS" if set(lenses.values()) == {"PASS"} else "FAIL"
    print(json.dumps({"verdict": verdict, "lenses": lenses}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
