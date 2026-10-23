# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Keep only the retro's changes that cite step 1's numbers as step 1 gave them, as JSON.

``vet.py --metrics JSON`` reads the ``changes`` agent's output ``{"changes": [...]}`` on stdin and
step 1's ``metrics`` (``{key: number}``) from ``--metrics``. A change is kept only when it cites
at least one key and every key it cites is in step 1 with the same value (both rounded to 2
places); otherwise it is dropped with a reason. The kept ones are cut to five and numbered 1…n.

It prints ``{"count", "kept", "dropped", "message"}``: ``kept`` holds each kept change with its
number ``n``, ``dropped`` each dropped one's ``title`` and ``reason``, and ``message`` is the
owner's gate text (the numbered changes with their evidence, then the dropped ones). Input that
is not JSON, or not of that shape, exits 2.
"""

import argparse
import json
import sys
from typing import TypeGuard

Change = dict[str, object]
Metrics = dict[str, object]

MAX_CHANGES = 5
MAX_MESSAGE = 16000
FIELDS = ("title", "kind", "change", "metrics", "links", "expected_effect", "how_to_tell")
NONE_KEPT = "No change kept: the retro proposes nothing this time."


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _shown(value: object) -> str:
    """A number as the owner reads it (``3``, ``0.25``); anything else as its repr."""
    if not _is_number(value):
        return repr(value)
    rounded = round(value, 2)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def _is_same(cited: object, given: object) -> bool:
    if not _is_number(cited) or not _is_number(given):
        return False
    return round(cited, 2) == round(given, 2)


def _why_dropped(change: Change, metrics: Metrics) -> str:
    """Why ``change`` does not stand on step 1's numbers; empty when it does."""
    refs = change.get("metrics")
    if not isinstance(refs, list) or not refs:
        return "cites no step 1 number"
    for ref in refs:
        key = ref.get("key") if isinstance(ref, dict) else None
        value = ref.get("value") if isinstance(ref, dict) else None
        if not isinstance(key, str) or key not in metrics:
            return f"cites {key}, not in step 1"
        if not _is_same(value, metrics[key]):
            return f"cites {_shown(value)} for {key}, step 1 has {_shown(metrics[key])}"
    return ""


def _section(change: Change) -> list[str]:
    """One kept change, numbered, with its evidence, links and expected effect."""
    lines = [f"{change['n']}. {change['title']} ({change['kind']})", f"   {change['change']}"]
    lines.append("   Evidence:")
    refs = change["metrics"]
    for ref in refs if isinstance(refs, list) else ():
        lines.append(f"   - {ref['key']} = {_shown(ref['value'])}")
    links = change["links"]
    if isinstance(links, list) and links:
        lines.append(f"   Links: {', '.join(str(link) for link in links)}")
    lines.append(f"   Expected effect: {change['expected_effect']}")
    lines.append(f"   How to tell: {change['how_to_tell']}")
    return lines


def _message(kept: list[Change], dropped: list[dict[str, str]]) -> str:
    lines: list[str] = []
    if kept:
        lines.append(f"The retro proposes {len(kept)} changes, each citing step 1's numbers:")
        for change in kept:
            lines += ["", *_section(change)]
    else:
        lines.append(NONE_KEPT)
    if dropped:
        lines += ["", f"Dropped ({len(dropped)}):"]
        lines += [f"- {item['title']}: {item['reason']}" for item in dropped]
    return "\n".join(lines)[:MAX_MESSAGE]


def vet(changes: list[object], metrics: Metrics) -> dict[str, object]:
    """``changes`` checked against step 1's ``metrics``: kept ones numbered, the rest dropped."""
    kept: list[Change] = []
    dropped: list[dict[str, str]] = []
    for change in changes:
        if not isinstance(change, dict):
            dropped.append({"title": "", "reason": "not a change object"})
            continue
        title = str(change.get("title") or "")
        reason = _why_dropped(change, metrics)
        if not reason and len(kept) >= MAX_CHANGES:
            reason = "over the five-change cap"
        if reason:
            dropped.append({"title": title, "reason": reason})
        else:
            kept.append({"n": len(kept) + 1} | {name: change.get(name, "") for name in FIELDS})
    return {
        "count": len(kept),
        "kept": kept,
        "dropped": dropped,
        "message": _message(kept, dropped),
    }


def _read(text: str, what: str) -> dict[str, object] | str:
    """``text`` as a JSON object, or what is wrong with it."""
    try:
        found = json.loads(text)
    except ValueError:
        return f"{what} is not JSON"
    return found if isinstance(found, dict) else f"{what} is not a JSON object"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="vet.py")
    parser.add_argument("--metrics", required=True)
    given = parser.parse_args(argv)
    metrics = _read(given.metrics, "--metrics")
    output = _read(sys.stdin.read(), "stdin")
    changes = output.get("changes") if isinstance(output, dict) else None
    problem = next((found for found in (metrics, output) if isinstance(found, str)), "")
    if not problem and not isinstance(changes, list):
        problem = "stdin has no changes list"
    if problem or not isinstance(metrics, dict) or not isinstance(changes, list):
        print(f"vet.py: {problem}", file=sys.stderr)
        return 2
    print(json.dumps(vet(changes, metrics)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
