import sqlite3

import pytest

from agent_hub.storage.engine import switch_to_wal


def _error(message: str, code: int) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError(message)
    error.sqlite_errorcode = code
    return error


class ScriptedCursor:
    """Raises the scripted errors in turn, then succeeds; records every statement."""

    def __init__(self, errors: list[sqlite3.OperationalError]) -> None:
        self.errors = errors
        self.statements: list[str] = []

    def execute(self, sql: str) -> object:
        self.statements.append(sql)
        if self.errors:
            raise self.errors.pop(0)
        return self


class FakeTime:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _busy() -> sqlite3.OperationalError:
    return _error("database is locked", sqlite3.SQLITE_BUSY)


def test_switches_after_backing_off_when_busy_a_few_times() -> None:
    cursor = ScriptedCursor([_busy(), _busy(), _busy()])
    fake_time = FakeTime()

    switch_to_wal(cursor, 5000, sleep=fake_time.sleep, clock=fake_time.clock)

    assert cursor.statements == ["PRAGMA journal_mode=WAL"] * 4
    assert len(fake_time.sleeps) == 3
    assert all(0.001 <= seconds <= 0.02 for seconds in fake_time.sleeps)


def test_raises_at_once_when_error_is_not_busy() -> None:
    cursor = ScriptedCursor([_error("disk I/O error", sqlite3.SQLITE_IOERR)])
    fake_time = FakeTime()

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        switch_to_wal(cursor, 5000, sleep=fake_time.sleep, clock=fake_time.clock)

    assert len(cursor.statements) == 1
    assert fake_time.sleeps == []


def test_raises_busy_when_deadline_passes() -> None:
    cursor = ScriptedCursor([_busy() for _ in range(1000)])
    fake_time = FakeTime()

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        switch_to_wal(cursor, 100, sleep=fake_time.sleep, clock=fake_time.clock)

    assert fake_time.now >= 0.1
    assert fake_time.now - fake_time.sleeps[-1] < 0.1  # the last retry started before the deadline
    assert cursor.errors  # it stopped long before running out of scripted errors
