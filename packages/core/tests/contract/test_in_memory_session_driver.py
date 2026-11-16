"""The ``SessionDriver`` contract against the in-memory fake (AC-165.2, core half)."""

import pytest

from agent_hub.core.agent_sessions.driver import SessionDriver
from agent_hub.core.testing.session_driver_contract import (
    ContractScenario,
    SessionDriverContract,
    contract_scenario,
)
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver


@pytest.fixture
def scenario() -> ContractScenario:
    return contract_scenario()


@pytest.fixture
def session_driver(scenario: ContractScenario) -> SessionDriver:
    return InMemorySessionDriver(replies=scenario.replies)


class TestInMemorySessionDriver(SessionDriverContract):
    """The fake honours the contract."""

    pytestmark = pytest.mark.anyio
