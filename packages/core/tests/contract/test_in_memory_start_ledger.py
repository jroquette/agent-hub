"""The ``StartLedger`` contract against ``InMemoryStartLedger`` (AGH-481)."""

import pytest

from agent_hub.core.schedules.scheduled_starts import StartLedger
from agent_hub.core.testing.schedule_fakes import InMemoryStartLedger
from agent_hub.core.testing.start_ledger_contract import StartLedgerContract


@pytest.fixture
def start_ledger() -> StartLedger:
    return InMemoryStartLedger()


@pytest.fixture
def ledger_hubs() -> tuple[str, str]:
    return "/hubs/demo", "/hubs/other"


class TestInMemoryStartLedger(StartLedgerContract):
    """Every contract test, on the fake."""
