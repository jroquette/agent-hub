"""Regenerate the generator's table of pre-parsed built-in workflows.

Reads every pack-level ``*.yaml`` built-in (the files discovery reads; hidden names skipped) with
the strict loader, never the cached one (which would read the table it rebuilds), and writes
``table_text`` to the generator package data file. Run it after any change to a built-in or to
the strict loader and commit the file; ``test_export_parsed_builtins.py`` fails until you do.
Run it as ``make parsed-builtins`` or ``python -m scripts.export_parsed_builtins`` from the
repo root.
"""

import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_hub.generator.parsed_builtins import TABLE_FILE, ParsedBuiltin, table_text
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import read_workflow_strictly

REPO_ROOT = Path(__file__).resolve().parent.parent
TABLE_PATH = Path("packages/generator/src/agent_hub/generator") / TABLE_FILE


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    """Write the table under ``root``; ``argv`` takes no arguments."""
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("usage: python -m scripts.export_parsed_builtins", file=sys.stderr)
        return 2
    target = root / TABLE_PATH
    # newline="\n": the same bytes on every platform, so git sees no change.
    target.write_text(table_text(_entries()), encoding="utf-8", newline="\n")
    print(f"wrote {TABLE_PATH.as_posix()}")
    return 0


def _entries() -> list[ParsedBuiltin]:
    entries = []
    for path in sorted(BUILTIN_WORKFLOWS.glob("*/*.yaml")):
        if path.name.startswith(".") or path.parent.name.startswith("."):
            continue
        content = path.read_bytes()
        source = f"{path.parent.name}/{path.name}"
        loaded = read_workflow_strictly(content, source=source)
        entries.append(
            ParsedBuiltin(
                sha256=hashlib.sha256(content).hexdigest(),
                source=source,
                document=loaded.document,
                lines=loaded.lines,
            )
        )
    return entries


if __name__ == "__main__":
    sys.exit(main())
