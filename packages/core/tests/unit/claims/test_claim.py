"""A claim's stale rule (AGH-810b): AM-3 on a fixed clock and a fake process table."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agent_hub.core.claims.claim import (
    MAX_QUESTION,
    STALE_AFTER,
    Claim,
    Live,
    Stale,
    claim_state,
)

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
START = "Sat Nov 14 06:04:27 2026"
PID = 4242


class FakeProcesses:
    """A process table: pid to the start time ``ps -o lstart=`` prints."""

    def __init__(self, table: Mapping[int, str]) -> None:
        self._table = dict(table)

    def started(self, pid: int) -> str | None:
        return self._table.get(pid)


def a_claim(
    *, pid: int | None = PID, started: str | None = START, idle: timedelta = timedelta(0)
) -> Claim:
    return Claim(
        ticket="DEM-1",
        session="s-1",
        pid=pid,
        started=started,
        hub="/hubs/demo",
        claimed_at=NOW - idle - timedelta(hours=1),
        last_activity=NOW - idle,
    )


def test_is_live_when_process_runs_past_24_hours() -> None:
    claim = a_claim(idle=timedelta(hours=30))

    assert claim_state(claim, NOW, FakeProcesses({PID: START})) == Live()


def test_is_stale_when_process_gone() -> None:
    state = claim_state(a_claim(), NOW, FakeProcesses({}))

    assert isinstance(state, Stale)


def test_is_stale_when_pid_reused_by_another_start() -> None:
    state = claim_state(a_claim(), NOW, FakeProcesses({PID: "Sun Nov 15 11:00:00 2026"}))

    assert isinstance(state, Stale)


def test_is_stale_when_no_pid_and_idle_over_24_hours() -> None:
    claim = a_claim(pid=None, started=None, idle=STALE_AFTER + timedelta(seconds=1))

    assert isinstance(claim_state(claim, NOW, FakeProcesses({PID: START})), Stale)


def test_is_live_when_no_pid_and_idle_under_24_hours() -> None:
    claim = a_claim(pid=None, started=None, idle=STALE_AFTER)

    assert claim_state(claim, NOW, FakeProcesses({})) == Live()


@pytest.mark.parametrize(
    ("claim", "table", "words"),
    [
        (a_claim(), {}, ("process 4242", "not running")),
        (
            a_claim(),
            {PID: "Sun Nov 15 11:00:00 2026"},
            ("pid 4242", "Sun Nov 15 11:00:00 2026", START),
        ),
        (
            a_claim(pid=None, started=None, idle=timedelta(hours=25)),
            {},
            ("idle since 2026-11-14T11:00:00+00:00",),
        ),
    ],
    ids=["gone", "another_start", "idle"],
)
def test_names_the_reason_when_claim_stale(
    claim: Claim, table: Mapping[int, str], words: tuple[str, ...]
) -> None:
    state = claim_state(claim, NOW, FakeProcesses(table))

    assert isinstance(state, Stale)
    assert all(word in state.reason for word in words), state.reason


def test_refuses_pid_without_start_time_when_claim_built() -> None:
    with pytest.raises(ValidationError, match="pid and started"):
        a_claim(started=None)


OLD_CLAIM_JSON = """{
  "ticket": "DEM-1",
  "session": "s-1",
  "pid": 4242,
  "started": "Sat Nov 14 06:04:27 2026",
  "hub": "/hubs/demo",
  "claimed_at": "2026-11-15T11:00:00+00:00",
  "last_activity": "2026-11-15T12:00:00+00:00"
}"""


def test_reads_old_claim_when_question_fields_absent() -> None:
    claim = Claim.model_validate_json(OLD_CLAIM_JSON)

    assert claim.question is None
    assert claim.asked_at is None
    assert claim.title is None


def test_refuses_question_without_asked_at_when_validated() -> None:
    with pytest.raises(ValidationError, match="question and asked_at"):
        Claim.model_validate({**a_claim().model_dump(), "question": "Merge #41?"})


def test_refuses_asked_at_without_question_when_validated() -> None:
    with pytest.raises(ValidationError, match="question and asked_at"):
        Claim.model_validate({**a_claim().model_dump(), "asked_at": NOW})


def test_refuses_question_when_longer_than_max_question() -> None:
    with pytest.raises(ValidationError, match="question"):
        Claim.model_validate(
            {**a_claim().model_dump(), "question": "x" * (MAX_QUESTION + 1), "asked_at": NOW}
        )


def test_keeps_question_asked_at_and_title_when_set_together() -> None:
    claim = Claim.model_validate(
        {
            **a_claim().model_dump(),
            "question": "x" * MAX_QUESTION,
            "asked_at": NOW,
            "title": "DEM-1 login",
        }
    )

    assert (claim.question, claim.asked_at, claim.title) == ("x" * MAX_QUESTION, NOW, "DEM-1 login")
