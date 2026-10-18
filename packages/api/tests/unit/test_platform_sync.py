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
    """Answers ``hub sync`` with ``sync_exit``; ``git status`` lists ``notes.md`` (the owner's
    own edit) before the sync, and the pin and lock beside it after."""

    def __init__(self, *, sync_exit: int = 0) -> None:
        self.sync_exit = sync_exit
        self.calls: list[tuple[str, ...]] = []
        self.pin_seen: str | None = None

    def __call__(self, argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(argv))
        if argv[-1] == "sync":
            self.pin_seen = json.loads((cwd / "hub.json").read_text())["platform"]["version"]
            return subprocess.CompletedProcess(argv, self.sync_exit, "updated hub.lock\n", "")
        synced = any(call[-1] == "sync" for call in self.calls)
        status = " M notes.md\n" + (" M hub.json\n M hub.lock\n" if synced else "")
        return subprocess.CompletedProcess(argv, 0, status, "")


def test_changes_only_pin_when_text_pinned() -> None:
    previous, text = pinned_text(HUB_JSON, "0.16.0")

    assert previous == "0.14.0"
    assert text == HUB_JSON.replace("0.14.0", "0.16.0")


def test_refuses_pin_when_hub_json_has_no_platform() -> None:
    with pytest.raises(PlatformSyncError):
        pinned_text('{"schema_version": 1}', "0.16.0")


def test_pins_syncs_and_lists_changes_when_platform_synced(tmp_path: Path) -> None:
    (tmp_path / "hub.json").write_text(HUB_JSON)
    runner = FakeRunner()

    result = sync_platform(
        "h1", str(tmp_path), running_version="0.16.0", run=runner, program=("hub",)
    )

    assert runner.pin_seen == "0.16.0"
    assert ("hub", "sync") in runner.calls
    assert result.ok
    assert (result.previous_version, result.version) == ("0.14.0", "0.16.0")
    assert result.output == ("updated hub.lock",)
    assert result.changed_files == ("hub.json", "hub.lock")


def test_restores_old_pin_when_sync_fails(tmp_path: Path) -> None:
    (tmp_path / "hub.json").write_text(HUB_JSON)

    result = sync_platform(
        "h1", str(tmp_path), running_version="0.16.0", run=FakeRunner(sync_exit=3), program=("hub",)
    )

    assert not result.ok
    assert result.exit_code == 3
    assert result.version == "0.14.0"
    assert (tmp_path / "hub.json").read_text() == HUB_JSON


# AC-PG-23.3: hub.json that is not JSON, or has no platform object, cannot be pinned.
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('{"platform": {"version": "0.14.0"', "hub.json is not valid JSON"),
        ("", "hub.json is not valid JSON"),
        ('["platform"]', "hub.json has no platform object"),
        ('{"platform": "0.14.0"}', "hub.json has no platform object"),
        ('{"platform": null}', "hub.json has no platform object"),
    ],
)
def test_refuses_pin_when_hub_json_cannot_be_pinned(text: str, reason: str) -> None:
    with pytest.raises(PlatformSyncError, match=f"^{reason}$"):
        pinned_text(text, "0.16.0")


# AC-PG-23.3: a refused hub.json is left byte for byte, and hub sync never runs.
@pytest.mark.parametrize("text", ["not json\n", '{"schema_version": 1}\n'])
def test_writes_nothing_and_runs_nothing_when_hub_json_refused(tmp_path: Path, text: str) -> None:
    (tmp_path / "hub.json").write_text(text)
    runner = FakeRunner()

    with pytest.raises(PlatformSyncError):
        sync_platform("h1", str(tmp_path), running_version="0.16.0", run=runner, program=("hub",))

    assert runner.calls == []
    assert (tmp_path / "hub.json").read_text() == text
    assert sorted(path.name for path in tmp_path.iterdir()) == ["hub.json"]


# AC-PG-23.3: a hub.json that cannot be read (missing, or a folder) is refused before any run.
@pytest.mark.parametrize("shape", ["missing", "folder"])
def test_refuses_sync_when_hub_json_unreadable(tmp_path: Path, shape: str) -> None:
    if shape == "folder":
        (tmp_path / "hub.json").mkdir()
    runner = FakeRunner()

    with pytest.raises(PlatformSyncError, match="^hub.json cannot be read$"):
        sync_platform("h1", str(tmp_path), running_version="0.16.0", run=runner, program=("hub",))

    assert runner.calls == []


class _BrokenSync(FakeRunner):
    """``hub sync`` cannot start or does not finish; ``git status`` answers as ``FakeRunner``."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def __call__(self, argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if argv[-1] == "sync":
            self.calls.append(tuple(argv))
            raise self.error
        return super().__call__(argv, cwd)


# AC-PG-23.3: hub sync that cannot start or times out also puts the old pin back.
@pytest.mark.parametrize(
    ("error", "line"),
    [
        (subprocess.TimeoutExpired(("hub", "sync"), 120.0), "hub sync did not finish in time"),
        (
            FileNotFoundError(2, "No such file or directory"),
            "hub sync could not start: No such file or directory",
        ),
    ],
)
def test_restores_old_pin_when_sync_cannot_run(tmp_path: Path, error: Exception, line: str) -> None:
    (tmp_path / "hub.json").write_text(HUB_JSON)

    result = sync_platform(
        "h1", str(tmp_path), running_version="0.16.0", run=_BrokenSync(error), program=("hub",)
    )

    assert (result.ok, result.exit_code, result.output) == (False, 1, (line,))
    assert (result.version, result.changed_files) == ("0.14.0", ())
    assert (tmp_path / "hub.json").read_text() == HUB_JSON
