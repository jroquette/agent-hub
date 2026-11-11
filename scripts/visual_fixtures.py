"""Regenerate the visual tests' API fixtures (AGH-817).

The demo server has no Linear key, so a feature's tickets come from the plan there and no ticket
is ever done. The large feature's visual test (``apps/web/e2e/visual/feature-detail.spec.ts``)
serves its tickets route as ``hub web`` answers it once Linear is read: this script builds that
answer with core's own ``feature_tickets``, from ``seed_demo``'s large feature folder and its
synthetic Linear read (``large_linear``), at the visual tests' frozen instant. Run it after a
change to either, or to the tickets view, and commit the file;
``tests/unit/scripts/test_visual_fixtures.py`` fails until you do.
Run it as ``python -m scripts.visual_fixtures`` from the repo root.
"""

import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from agent_hub.core.features.feature_tickets import feature_tickets
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.hub_config.model import Tracker
from agent_hub.core.tracker.tracker_reader import IssueSummary, TicketSnapshot
from agent_hub.generator.feature_files import read_feature_folder
from scripts.seed_demo import DEMO_PROJECT, LARGE_FEATURE, large_feature_files, large_linear

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = Path("apps/web/e2e/visual/fixtures") / f"{LARGE_FEATURE}-tickets.json"
# The visual tests' frozen clock (apps/web/e2e/visual/screen.ts), and a Linear read 30 s before.
FROZEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
READ_AT = FROZEN - timedelta(seconds=30)


def fixture_text() -> str:
    """The large feature's ``GET /features/demo/ledger-sync/tickets`` answer, as JSON."""
    with tempfile.TemporaryDirectory(prefix="visual-fixtures-") as scratch:
        hub = Path(scratch)
        for path, text in large_feature_files(PurePosixPath(".")).items():
            target = hub / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        folder = read_feature_folder(hub, LARGE_FEATURE, tickets=True)
    if folder is None:
        raise RuntimeError(f"the {LARGE_FEATURE} folder was not read")
    snapshot = TicketSnapshot(
        summaries=tuple(IssueSummary.model_validate(issue) for issue in large_linear()),
        missing=(),
        external=(),
    )
    read = SnapshotRead(
        snapshot=snapshot,
        source="linear",
        stale=False,
        as_of=READ_AT,
        failure=None,
        detail=None,
        http_status=None,
    )
    tickets = feature_tickets(
        folder,
        read,
        project=DEMO_PROJECT,
        tracker=Tracker.model_validate({"kind": "linear", "team": "AGH"}),
        now=FROZEN,
    )
    return json.dumps(tickets.model_dump(mode="json", by_alias=True), indent=2) + "\n"


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    """Write the fixtures under ``root``; ``argv`` takes no arguments."""
    args = sys.argv[1:] if argv is None else argv
    if args:
        print("usage: python -m scripts.visual_fixtures", file=sys.stderr)
        return 2
    target = root / FIXTURE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": the same bytes on every platform, so git sees no change.
    target.write_text(fixture_text(), encoding="utf-8", newline="\n")
    print(f"wrote {FIXTURE_PATH.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
