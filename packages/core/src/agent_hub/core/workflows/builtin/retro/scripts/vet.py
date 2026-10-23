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

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # typing.TypeGuard is 3.10+: the hub's copy also imports on Python 3.9.
    from typing import TypeGuard

Change = dict[str, object]
Metrics = dict[str, object]

MAX_CHANGES = 5
MAX_MESSAGE = 16000
FIELDS = ("title", "kind", "change", "metrics", "links", "expected_effect", "how_to_tell")
NONE_KEPT = "No change kept: the retro proposes nothing this time."
CUT = "(cut)"
# The changes output format's caps; the message cuts the free text below them when it must.
TEXT_CAPS = {
    "title": 120,
    "key": 120,
    "change": 1500,
    "link": 310,
    "expected_effect": 600,
    "how_to_tell": 400,
}
MAX_LINKS = 5
MAX_DROPPED_SHOWN = 10
SCALES = (1.0, 0.5, 0.25, 0.1, 0.05)


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


def _cut(value: object, limit: int) -> str:
    """``value`` as text, at most ``limit`` characters, marked when cut."""
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]} {CUT}"


def _section(change: Change, scale: float) -> list[str]:
    """One kept change, numbered, with its evidence, links and expected effect; its free text
    cut to ``scale`` of its format's cap, its title and evidence never cut below that cap."""
    limit = {name: max(20, int(cap * scale)) for name, cap in TEXT_CAPS.items()}
    title = _cut(change["title"], TEXT_CAPS["title"])
    lines = [
        f"{change['n']}. {title} ({change['kind']})",
        f"   {_cut(change['change'], limit['change'])}",
    ]
    lines.append("   Evidence:")
    refs = change["metrics"]
    for ref in refs if isinstance(refs, list) else ():
        lines.append(f"   - {_cut(ref['key'], TEXT_CAPS['key'])} = {_shown(ref['value'])}")
    links = change["links"]
    if isinstance(links, list) and links:
        shown = ", ".join(_cut(link, limit["link"]) for link in links[:MAX_LINKS])
        lines.append(f"   Links: {shown}")
    lines.append(f"   Expected effect: {_cut(change['expected_effect'], limit['expected_effect'])}")
    lines.append(f"   How to tell: {_cut(change['how_to_tell'], limit['how_to_tell'])}")
    return lines


def _render(kept: list[Change], dropped: list[dict[str, str]], scale: float) -> str:
    lines: list[str] = []
    if kept:
        lines.append(f"The retro proposes {len(kept)} changes, each citing step 1's numbers:")
        for change in kept:
            lines += ["", *_section(change, scale)]
    else:
        lines.append(NONE_KEPT)
    if dropped:
        lines += ["", f"Dropped ({len(dropped)}):"]
        lines += [
            f"- {_cut(item['title'], TEXT_CAPS['title'])}: {_cut(item['reason'], 200)}"
            for item in dropped[:MAX_DROPPED_SHOWN]
        ]
        lines += [f"- and {len(dropped) - MAX_DROPPED_SHOWN} more"] * (
            len(dropped) > MAX_DROPPED_SHOWN
        )
    return "\n".join(lines)


def _message(kept: list[Change], dropped: list[dict[str, str]]) -> str:
    """The gate's text: every kept change and the dropped ones, each change's free text cut
    further until all of it fits, so the owner never keeps a change the text did not show."""
    for scale in SCALES:
        text = _render(kept, dropped, scale)
        if len(text) <= MAX_MESSAGE:
            return text
    return f"{text[: MAX_MESSAGE - len(CUT) - 1]} {CUT}"


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
