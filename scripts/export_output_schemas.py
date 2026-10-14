"""Regenerate the shipped JSON Schemas of the agent outputs from their models (AGH-139 S8).

Writes ``export_output_schema_text(kind)`` for each kind to its core package data file. Run it
after any change to ``ReviewOutput`` or ``EvalOutput`` and commit both files;
``test_agent_outputs.py`` fails until you do.
Run it as ``make output-schemas`` or ``python -m scripts.export_output_schemas`` from the repo
root.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from agent_hub.core.features.agent_outputs import OUTPUT_SCHEMA_FILES, export_output_schema_text

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_SCHEMA_DIR = Path("packages/core/src/agent_hub/core/features")


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    """Write both schemas under ``root``; ``argv`` takes no arguments."""
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("usage: python -m scripts.export_output_schemas", file=sys.stderr)
        return 2
    for kind, name in OUTPUT_SCHEMA_FILES.items():
        relative = OUTPUT_SCHEMA_DIR / name
        # newline="\n": the same bytes on every platform, so git sees no change.
        (root / relative).write_text(
            export_output_schema_text(kind), encoding="utf-8", newline="\n"
        )
        print(f"wrote {relative.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
