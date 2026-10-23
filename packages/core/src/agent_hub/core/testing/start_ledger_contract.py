"""The ``StartLedger`` contract (ADR 0048): every implementation passes these tests.

A test module subclasses ``StartLedgerContract`` and provides two fixtures: ``start_ledger``,
the ledger under test, and ``ledger_hubs``, two hub folders it may keep state for.
"""

from datetime import UTC, datetime

import pytest

from agent_hub.core.schedules.scheduled_starts import StartLedger, StartState

SLOT = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
STATE = StartState(
    slots={"retro": SLOT},
    seen={"verify merge demo-api": ("a" * 40,), "triage ci_red demo-api": ("101", "100")},
    marks={"notes pr_opened demo-api": 9, "triage ci_red demo-api": 99},
)


class _RefusedError(Exception):
    """A change that fails on purpose."""


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


def _read(ledger: StartLedger, hub: str) -> StartState:
    return ledger.update(hub, lambda state: (state, state))


class StartLedgerContract:
    """The behaviour every ``StartLedger`` shares."""

    def test_reads_empty_state_when_schedule_ledger_is_absent(
        self, start_ledger: StartLedger, ledger_hubs: tuple[str, str]
    ) -> None:
        _check(_read(start_ledger, ledger_hubs[0]) == StartState(), "an absent ledger is empty")

    def test_reads_back_written_state_when_schedule_ledger_updated(
        self, start_ledger: StartLedger, ledger_hubs: tuple[str, str]
    ) -> None:
        start_ledger.update(ledger_hubs[0], lambda _: (STATE, None))

        _check(_read(start_ledger, ledger_hubs[0]) == STATE, "the state reads back")

    def test_returns_change_result_when_schedule_ledger_updated(
        self, start_ledger: StartLedger, ledger_hubs: tuple[str, str]
    ) -> None:
        result = start_ledger.update(ledger_hubs[0], lambda state: (state, "result"))

        _check(result == "result", "the change's result is returned")

    def test_keeps_state_when_schedule_ledger_change_raises(
        self, start_ledger: StartLedger, ledger_hubs: tuple[str, str]
    ) -> None:
        start_ledger.update(ledger_hubs[0], lambda _: (STATE, None))

        def refuse(_: StartState) -> tuple[StartState, None]:
            raise _RefusedError

        with pytest.raises(_RefusedError):
            start_ledger.update(ledger_hubs[0], refuse)

        _check(_read(start_ledger, ledger_hubs[0]) == STATE, "the state reads back")

    def test_keeps_hubs_apart_when_two_schedule_ledgers_updated(
        self, start_ledger: StartLedger, ledger_hubs: tuple[str, str]
    ) -> None:
        start_ledger.update(ledger_hubs[0], lambda _: (STATE, None))

        _check(_read(start_ledger, ledger_hubs[1]) == StartState(), "each hub has its own state")
