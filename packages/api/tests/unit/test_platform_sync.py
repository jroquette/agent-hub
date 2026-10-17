import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_hub.api.platform_sync import PlatformSyncError, pinned_text, sync_platform

HUB_JSON = (
    '{\n  "schema_version": 1,\n  "platform": {\n    "version": "0.14.0"\n  },\n  "x": 1\n}\n'
)


class FakeRunner:
    """Answers ``hub sync`` with ``sync_exit`` and ``git status`` with one changed file."""

    def __init__(self, *, sync_exit: int = 0) -> None:
        self.sync_exit = sync_exit
        self.calls: list[tuple[str, ...]] = []
        self.pin_seen: str | None = None

    def __call__(self, argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(argv))
        if argv[-1] == "sync":
            self.pin_seen = json.loads((cwd / "hub.json").read_text())["platform"]["version"]
            return subprocess.CompletedProcess(argv, self.sync_exit, "updated hub.lock\n", "")
        return subprocess.CompletedProcess(argv, 0, " M hub.json\n M hub.lock\n", "")


def test_pinned_text_changes_only_the_pin() -> None:
    previous, text = pinned_text(HUB_JSON, "0.16.0")

    assert previous == "0.14.0"
    assert text == HUB_JSON.replace("0.14.0", "0.16.0")


def test_pinned_text_refuses_a_hub_json_without_platform() -> None:
    with pytest.raises(PlatformSyncError):
        pinned_text('{"schema_version": 1}', "0.16.0")


def test_sync_platform_pins_then_syncs_and_lists_the_changes(tmp_path: Path) -> None:
    (tmp_path / "hub.json").write_text(HUB_JSON)
    runner = FakeRunner()

    result = sync_platform(
        "h1", str(tmp_path), running_version="0.16.0", run=runner, program=("hub",)
    )

    assert runner.pin_seen == "0.16.0"
    assert runner.calls[0] == ("hub", "sync")
    assert result.ok
    assert (result.previous_version, result.version) == ("0.14.0", "0.16.0")
    assert result.output == ("updated hub.lock",)
    assert result.changed_files == ("hub.json", "hub.lock")


def test_a_failed_sync_puts_the_old_pin_back(tmp_path: Path) -> None:
    (tmp_path / "hub.json").write_text(HUB_JSON)

    result = sync_platform(
        "h1", str(tmp_path), running_version="0.16.0", run=FakeRunner(sync_exit=3), program=("hub",)
    )

    assert not result.ok
    assert result.exit_code == 3
    assert result.version == "0.14.0"
    assert (tmp_path / "hub.json").read_text() == HUB_JSON
