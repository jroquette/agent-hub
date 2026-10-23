"""Rewrite the flow table in ``docs/USING.md`` from the built-in workflows (AGH-495).

The table sits between ``<!-- flow-catalog:start -->`` and ``<!-- flow-catalog:end -->``; the
generator's ``flow_catalog`` builds it from each built-in's description, the skill templates and
the packs' gates, so nobody keeps it by hand. Run ``make llms-txt`` (which runs this first) after
a pack changes and commit the doc; ``test_build_flow_catalog.py`` (in ``make check-fast``) fails
until you do.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from agent_hub.generator.flow_catalog import builtin_flows, flow_table

REPO_ROOT = Path(__file__).resolve().parent.parent
USING_DOC = REPO_ROOT / "docs" / "USING.md"
START = "<!-- flow-catalog:start -->"
END = "<!-- flow-catalog:end -->"


def with_catalog(text: str, table: str) -> str | None:
    """``text`` with ``table`` between the markers; None when they are missing or out of order."""
    start = text.find(START)
    end = text.find(END)
    if start < 0 or end < start:
        return None
    return f"{text[: start + len(START)]}\n{table}{text[end:]}"


def catalog_block(text: str) -> str | None:
    """What sits between the markers, without the newline after the start marker."""
    start = text.find(START)
    end = text.find(END)
    if start < 0 or end < start:
        return None
    return text[start + len(START) + 1 : end]


def main(argv: Sequence[str] = ()) -> int:
    path = Path(argv[0]) if argv else USING_DOC
    text = path.read_text(encoding="utf-8")
    updated = with_catalog(text, flow_table(builtin_flows()))
    if updated is None:
        print(f"build_flow_catalog: no flow-catalog markers in {path}", file=sys.stderr)
        return 1
    if updated != text:
        path.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
