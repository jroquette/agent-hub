"""Regenerate the generator's table of pre-parsed built-in workflows (AGH-636).

Stub for the RED tests of plan commit 32; plan commit 33 implements it.
Run it as ``make parsed-builtins`` or ``python -m scripts.export_parsed_builtins`` from the
repo root.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from agent_hub.generator.parsed_builtins import TABLE_FILE

REPO_ROOT = Path(__file__).resolve().parent.parent
TABLE_PATH = Path("packages/generator/src/agent_hub/generator") / TABLE_FILE


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    """Write the table under ``root``; ``argv`` takes no arguments."""
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
