# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read the discovery the implementing session reported, from its reply on stdin, as JSON.

``discovery.py < reply`` reads the reply's last line holding a JSON object (backticks around it
ignored, as ``hub step verdict`` reads it) and prints ``{"discovery"}``: that object's
``discovery`` as one line of at most ``MAX_CHARS`` characters, control characters dropped, or
``""`` when it has none (no JSON line, no key, a blank or non-text value). A discovery is a
broken assumption of the plan; the run loops back to preflight with it. Exits 0 either way.
"""

import json
import sys

MAX_CHARS = 1000


def last_json_line(text: str) -> dict[str, object] | None:
    for line in reversed(text.strip().splitlines()):
        candidate = line.strip().strip("`")
        if not (candidate.startswith("{") and candidate.endswith("}")):
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        return value if isinstance(value, dict) else None
    return None


def one_line(text: str) -> str:
    kept = "".join(c for c in text if c.isprintable() or c.isspace())
    return " ".join(kept.split())[:MAX_CHARS]


def main() -> int:
    found = last_json_line(sys.stdin.read()) or {}
    value = found.get("discovery")
    print(json.dumps({"discovery": one_line(value) if isinstance(value, str) else ""}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
