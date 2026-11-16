"""A 5-field cron parser on the stdlib, evaluated in UTC (ADR 0048).

Fields: minute, hour, day of month, month, day of week; each a comma list of ``*``, ``N``,
``A-B``, ``*/S`` or ``A-B/S``. No names, macros, ``L``/``W``/``#``/``?``, seconds or zones.
Day of month and day of week follow Vixie cron: when both are restricted (neither starts with
``*``) a day matches either, else both.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final

from agent_hub.core.errors import AgentHubError

MAX_CRON_CHARS: Final = 100
# How far a slot is looked for: a cron that fires less often than this is treated as never.
HORIZON_DAYS: Final = 366 * 5
_FIELDS: Final = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 7),
)
_SUNDAY_ALIAS: Final = 7


class CronError(AgentHubError):
    """A cron text that is not 5 valid numeric fields; the message names the field."""


@dataclass(frozen=True)
class CronSchedule:
    """The minutes, hours, days, months and weekdays (0 is Sunday) a cron fires on, in UTC."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    days_restricted: bool
    weekdays_restricted: bool

    def matches(self, when: datetime) -> bool:
        """Whether the minute ``when`` falls in (read in UTC) is a slot."""
        moment = _utc(when)
        return (
            moment.minute in self.minutes
            and moment.hour in self.hours
            and self._day_matches(moment.date())
        )

    def next_after(self, after: datetime) -> datetime | None:
        """The first slot strictly later than ``after``; None when none is within the horizon."""
        start = _minute_floor(after) + timedelta(minutes=1)
        hours, minutes = sorted(self.hours), sorted(self.minutes)
        for offset in range(HORIZON_DAYS):
            day = start.date() + timedelta(days=offset)
            if not self._day_matches(day):
                continue
            for hour in hours:
                for minute in minutes:
                    slot = datetime.combine(day, time(hour, minute), tzinfo=UTC)
                    if slot >= start:
                        return slot
        return None

    def latest_at_or_before(self, now: datetime) -> datetime | None:
        """The last slot at or before ``now``; None when none is within the horizon."""
        end = _minute_floor(now)
        hours, minutes = sorted(self.hours, reverse=True), sorted(self.minutes, reverse=True)
        for offset in range(HORIZON_DAYS):
            day = end.date() - timedelta(days=offset)
            if not self._day_matches(day):
                continue
            for hour in hours:
                for minute in minutes:
                    slot = datetime.combine(day, time(hour, minute), tzinfo=UTC)
                    if slot <= end:
                        return slot
        return None

    def _day_matches(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        in_days = day.day in self.days
        in_weekdays = (day.weekday() + 1) % 7 in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return in_days or in_weekdays
        return in_days and in_weekdays


def parse_cron(text: str) -> CronSchedule:
    """The schedule of a 5-field cron text; ``CronError`` naming the field otherwise."""
    if len(text) > MAX_CRON_CHARS:
        raise CronError(f"cron is longer than {MAX_CRON_CHARS} characters")
    fields = text.split()
    if len(fields) != len(_FIELDS):
        raise CronError(
            "cron needs 5 fields (minute hour day month weekday),"
            f" separated by spaces; got {len(fields)}"
        )
    values = [
        _field_values(field, name=name, low=low, high=high)
        for field, (name, low, high) in zip(fields, _FIELDS, strict=True)
    ]
    weekdays = frozenset(0 if day == _SUNDAY_ALIAS else day for day in values[4])
    return CronSchedule(
        minutes=values[0],
        hours=values[1],
        days=values[2],
        months=values[3],
        weekdays=weekdays,
        days_restricted=not fields[2].startswith("*"),
        weekdays_restricted=not fields[4].startswith("*"),
    )


def _field_values(field: str, *, name: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in field.split(","):
        values.update(_part_values(part, name=name, low=low, high=high))
    return frozenset(values)


def _part_values(part: str, *, name: str, low: int, high: int) -> range:
    span, slash, step_text = part.partition("/")
    step = _number(step_text, name=name) if slash else 1
    if step < 1:
        raise CronError(f"cron field {name}: the step must be 1 or more, not {step_text}")
    if span == "*":
        return range(low, high + 1, step)
    first_text, dash, last_text = span.partition("-")
    first = _number(first_text, name=name)
    last = _number(last_text, name=name) if dash else first
    if slash and not dash:
        raise CronError(f"cron field {name}: a step needs * or a range, not {part}")
    for value in (first, last):
        if not low <= value <= high:
            raise CronError(f"cron field {name}: {value} is outside {low}-{high}")
    if first > last:
        raise CronError(f"cron field {name}: the range {span} runs backwards")
    return range(first, last + 1, step)


def _number(text: str, *, name: str) -> int:
    if not text.isascii() or not text.isdigit():
        raise CronError(f"cron field {name}: {text or 'an empty part'} is not a number")
    return int(text)


def _utc(when: datetime) -> datetime:
    # A naive time is read as UTC, never as the machine's local time.
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _minute_floor(when: datetime) -> datetime:
    return _utc(when).replace(second=0, microsecond=0)
