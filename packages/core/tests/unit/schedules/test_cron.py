from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.schedules.cron import CronError, parse_cron


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_finds_next_monday_slot_when_weekly_schedule_cron_parsed() -> None:
    weekly = parse_cron("0 9 * * 1")

    # 2026-10-22 is a Thursday; the next Monday is 2026-10-26.
    assert weekly.next_after(at("2026-10-22T12:34:56")) == at("2026-10-26T09:00")
    assert weekly.next_after(at("2026-10-26T09:00")) == at("2026-11-02T09:00")


def test_finds_latest_slot_at_or_before_when_schedule_clock_is_on_the_slot() -> None:
    weekly = parse_cron("0 9 * * 1")

    assert weekly.latest_at_or_before(at("2026-10-26T09:00:30")) == at("2026-10-26T09:00")
    assert weekly.latest_at_or_before(at("2026-10-26T08:59")) == at("2026-10-19T09:00")


def test_matches_either_day_field_when_schedule_cron_restricts_both() -> None:
    both = parse_cron("0 0 13 * 5")
    day_only = parse_cron("0 0 13 * *")

    assert both.matches(at("2026-11-13T00:00"))  # a Friday the 13th
    assert both.matches(at("2026-10-13T00:00"))  # the 13th, a Tuesday
    assert both.matches(at("2026-10-23T00:00"))  # a Friday, the 23rd
    assert not both.matches(at("2026-10-22T00:00"))
    assert not day_only.matches(at("2026-10-23T00:00"))


def test_expands_steps_and_ranges_when_schedule_cron_uses_them() -> None:
    schedule = parse_cron("*/15 8-10 1,15 1-12/6 0,7")

    assert schedule.minutes == frozenset({0, 15, 30, 45})
    assert schedule.hours == frozenset({8, 9, 10})
    assert schedule.days == frozenset({1, 15})
    assert schedule.months == frozenset({1, 7})
    assert schedule.weekdays == frozenset({0})
    assert schedule.days_restricted
    assert schedule.weekdays_restricted
    assert not parse_cron("* * */2 * *").days_restricted


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("0 9 * *", "5 fields"),
        ("0 9 * * 1 2026", "5 fields"),
        ("60 9 * * 1", "minute"),
        ("0 9 * * MON", "weekday"),
        ("*/0 9 * * 1", "minute"),
        ("0 5-1 * * 1", "hour"),
        ("@weekly", "5 fields"),
        ("0 9 * * " + "1," * 48 + "1", "100 characters"),
    ],
)
def test_raises_cron_error_naming_field_when_schedule_cron_is_malformed(
    text: str, named: str
) -> None:
    with pytest.raises(CronError, match=named):
        parse_cron(text)


def test_returns_none_when_schedule_cron_never_fires() -> None:
    never = parse_cron("0 0 30 2 *")

    assert never.next_after(at("2026-01-01T00:00")) is None
    assert never.latest_at_or_before(at("2026-01-01T00:00")) is None


def _field(low: int, high: int) -> st.SearchStrategy[str]:
    number = st.integers(low, high)
    return st.one_of(
        st.just("*"),
        number.map(str),
        st.integers(1, high - low + 1).map(lambda step: f"*/{step}"),
        st.tuples(number, number).map(lambda pair: f"{min(pair)}-{max(pair)}"),
        st.lists(number, min_size=1, max_size=3).map(lambda items: ",".join(map(str, items))),
    )


CRONS = st.tuples(_field(0, 59), _field(0, 23), _field(1, 31), _field(1, 12), _field(0, 7)).map(
    " ".join
)
TIMES = st.datetimes(
    min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)
)


@settings(max_examples=60, deadline=None)
@given(text=CRONS, now=TIMES)
def test_brackets_now_between_slots_when_any_schedule_time_given_property(
    text: str, now: datetime
) -> None:
    schedule = parse_cron(text)
    latest = schedule.latest_at_or_before(now)
    following = schedule.next_after(now)

    if latest is not None:
        assert latest <= now
        assert schedule.matches(latest)
    if following is not None:
        assert following > now
        assert schedule.matches(following)
    if latest is not None and following is not None and following - latest < timedelta(days=1):
        minute = latest + timedelta(minutes=1)
        while minute < following:
            assert not schedule.matches(minute)
            minute += timedelta(minutes=1)
