"""The ``StartLedger`` contract and the file's own bounds, on ``FileStartLedger`` (AGH-481)."""

import fcntl
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_hub.api.start_ledger import MAX_LEDGER_BYTES, FileStartLedger
from agent_hub.core.schedules.scheduled_starts import (
    StartLedgerBusyError,
    StartLedgerError,
    StartState,
)
from agent_hub.core.testing.start_ledger_contract import StartLedgerContract

STATE = StartState(slots={"retro": datetime(2026, 10, 26, 9, 0, tzinfo=UTC)})


class TestFileStartLedger(StartLedgerContract):
    """Every contract test, on the file."""


def ledger_folder(hub: str) -> Path:
    return Path(hub, ".agent-runs", "schedules")


def keep(state: StartState) -> tuple[StartState, None]:
    return state, None


def test_raises_ledger_error_and_keeps_file_when_schedule_state_is_corrupt(
    ledger_hubs: tuple[str, str],
) -> None:
    folder = ledger_folder(ledger_hubs[0])
    folder.mkdir(parents=True)
    (folder / "state.json").write_bytes(b'{"version": 1, "slots": [')

    with pytest.raises(StartLedgerError, match="not valid"):
        FileStartLedger().update(ledger_hubs[0], lambda _: (STATE, None))

    assert (folder / "state.json").read_bytes() == b'{"version": 1, "slots": ['


def test_raises_ledger_error_when_schedule_state_is_over_the_cap(
    ledger_hubs: tuple[str, str],
) -> None:
    folder = ledger_folder(ledger_hubs[0])
    folder.mkdir(parents=True)
    (folder / "state.json").write_bytes(b" " * (MAX_LEDGER_BYTES + 1))

    with pytest.raises(StartLedgerError, match="larger than"):
        FileStartLedger().update(ledger_hubs[0], keep)


def test_raises_ledger_error_when_schedule_state_is_a_link(
    ledger_hubs: tuple[str, str], tmp_path: Path
) -> None:
    folder = ledger_folder(ledger_hubs[0])
    folder.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(STATE.model_dump_json())
    (folder / "state.json").symlink_to(elsewhere)

    with pytest.raises(StartLedgerError, match="cannot be read"):
        FileStartLedger().update(ledger_hubs[0], keep)


def test_raises_busy_when_schedule_state_lock_is_held(ledger_hubs: tuple[str, str]) -> None:
    ledger = FileStartLedger()
    ledger.update(ledger_hubs[0], lambda _: (STATE, None))
    held = os.open(ledger_folder(ledger_hubs[0]) / "state.lock", os.O_RDWR)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(StartLedgerBusyError):
            ledger.update(ledger_hubs[0], lambda _: (StartState(), None))
    finally:
        os.close(held)

    assert ledger.update(ledger_hubs[0], lambda state: (state, state)) == STATE


def test_writes_owner_only_file_when_schedule_state_saved(ledger_hubs: tuple[str, str]) -> None:
    FileStartLedger().update(ledger_hubs[0], lambda _: (STATE, None))

    folder = ledger_folder(ledger_hubs[0])
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "state.json").stat().st_mode) == 0o600
    assert sorted(path.name for path in folder.iterdir()) == ["state.json", "state.lock"]
    assert StartState.model_validate_json((folder / "state.json").read_bytes()) == STATE
