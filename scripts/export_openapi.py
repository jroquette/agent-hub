"""Write, or check, the committed OpenAPI document of the API (``packages/api/openapi.json``).

``python -m scripts.export_openapi`` writes the document the app builds, in the platform's JSON
byte form (sorted keys, LF, one final newline); ``--check`` compares instead and exits 1 naming
the file when it is stale. ``make openapi`` writes it and regenerates the web client;
``make openapi-check`` (in ``make check-fast``) checks both.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from agent_hub.api.app import create_app
from agent_hub.api.settings import DEFAULT_PORT, ApiSettings
from agent_hub.core.json_form import dump_json

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = Path("packages/api/openapi.json")
USAGE = "usage: python -m scripts.export_openapi [--check]"


def openapi_bytes() -> bytes:
    """The app's OpenAPI document; the settings do not change it, so placeholders do."""
    settings = ApiSettings(
        db_path=Path("agent-hub.db"),
        registry_path=Path("hubs.json"),
        port=DEFAULT_PORT,
        running_version="0.0.0",
    )
    return dump_json(create_app(settings).openapi())


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    """Write the document under ``root``, or with ``--check`` compare it; 2 on bad arguments."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["--check"]):
        print(USAGE, file=sys.stderr)
        return 2
    target = root / OPENAPI_PATH
    expected = openapi_bytes()
    if args:
        current = target.read_bytes() if target.is_file() else None
        if current != expected:
            print(f"{OPENAPI_PATH.as_posix()} is stale: run make openapi", file=sys.stderr)
            return 1
        return 0
    target.write_bytes(expected)
    print(f"wrote {OPENAPI_PATH.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
