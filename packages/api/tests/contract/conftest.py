"""The core contract suites run here against the api's adapters."""

from pathlib import Path

import pytest

from agent_hub.api.start_ledger import FileStartLedger
from agent_hub.core.schedules.scheduled_starts import StartLedger


@pytest.fixture
def start_ledger() -> StartLedger:
    return FileStartLedger()


@pytest.fixture
def ledger_hubs(tmp_path: Path) -> tuple[str, str]:
    hubs = (tmp_path / "demo-hub", tmp_path / "other-hub")
    for hub in hubs:
        hub.mkdir()
    return str(hubs[0]), str(hubs[1])
