# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Fold a round's check result and one lens's review into the next round's feedback, as JSON.

``feedback.py [--check JSON] [--notes JSON] < review`` reads one review on stdin (blank: the lens
did not run) and prints ``{"check", "findings", "omitted"}``: the check's ``passed``,
``exit_code`` and ``tail`` (from ``--check``, else from ``--notes``, else null); every finding of
``--notes`` and of the review, each tagged with its ``reviewer``, blocking first and otherwise in
order; then findings are dropped from the end, counted in ``omitted``, until the compact UTF-8
JSON holds at most ``BUDGET_BYTES``. ``--notes`` is an earlier call's output, so a second call
folds the second lens in. The budget keeps the next round's prompt far below its argument cap
(128 KiB). Text that is not JSON exits 2.
"""

from __future__ import annotations

import argparse
import json
import sys

BUDGET_BYTES = 32768


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def parsed(text: str, what: str) -> dict[str, object] | None:
    if not text.strip():
        return None
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise ValueError(f"feedback.py: {what} is not a JSON object")
    return value


def listed(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def findings_of(review: dict[str, object] | None) -> list[object]:
    if review is None:
        return []
    reviewer = review.get("reviewer")
    found = listed(review.get("findings"))
    return [{"reviewer": reviewer, **item} for item in found if isinstance(item, dict)]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="feedback.py")
    parser.add_argument("--check", default="")
    parser.add_argument("--notes", default="")
    given = parser.parse_args(argv)
    try:
        check = parsed(given.check, "--check")
        notes = parsed(given.notes, "--notes") or {}
        review = parsed(sys.stdin.read(), "the review")
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    kept = notes.get("check")
    if check is not None:
        kept = {key: check.get(key) for key in ("passed", "exit_code", "tail")}
    findings = [*listed(notes.get("findings")), *findings_of(review)]
    findings.sort(
        key=lambda item: not (isinstance(item, dict) and item.get("severity") == "blocking")
    )
    omitted = notes.get("omitted")
    print(within_budget(kept, findings, omitted if isinstance(omitted, int) else 0))
    return 0


def within_budget(check: object, findings: list[object], omitted: int) -> str:
    """The output, dropping findings from the end until it fits: each part measured once."""
    parts = [compact(item) for item in findings]
    sizes = [len(part.encode()) for part in parts]
    head = '{"check":' + compact(check) + ',"findings":['
    fixed = len(head.encode()) + len('],"omitted":}')
    total = sum(sizes) + max(0, len(parts) - 1)
    while parts and fixed + total + len(str(omitted)) > BUDGET_BYTES:
        total -= sizes.pop() + (1 if parts[1:] else 0)
        parts.pop()
        omitted += 1
    return head + ",".join(parts) + '],"omitted":' + str(omitted) + "}"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
