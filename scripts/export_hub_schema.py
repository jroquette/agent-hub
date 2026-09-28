"""Regenerate the shipped ``hub.json`` schema from ``HubConfig`` (P1).

Writes ``export_schema_text()`` to the core package data file. Run it after any change to a
``HubConfig`` model and commit the file; ``test_schema.py`` fails until you do.
Run it as ``make hub-schema`` or ``python -m scripts.export_hub_schema`` from the repo root.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from agent_hub.core.hub_config.schema import SCHEMA_FILE, export_schema_text

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path("packages/core/src/agent_hub/core/hub_config") / SCHEMA_FILE


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    """Write the schema under ``root``; ``argv`` takes no arguments."""
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("usage: python -m scripts.export_hub_schema", file=sys.stderr)
        return 2
    target = root / SCHEMA_PATH
    # newline="\n": the same bytes on every platform, so git sees no change.
    target.write_text(export_schema_text(), encoding="utf-8", newline="\n")
    print(f"wrote {SCHEMA_PATH.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
