from datetime import UTC, datetime, timedelta

import pytest

from agent_hub.core.sessions.session import Outcome, SessionStatus
from agent_hub.core.sessions.session_status import (
    END_AFTER,
    Activity,
    session_segments,
    session_status,
)

START = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def _activity(minutes: float, **fields: object) -> Activity:
    return Activity.model_validate({"at": START + timedelta(minutes=minutes)} | fields)


def _status_after(minutes: float, **flags: bool) -> SessionStatus:
    activity = [_activity(0), _activity(1)]
    now = START + timedelta(minutes=1 + minutes)
    segments = session_segments(activity, now=now)
    return session_status(
        segments,
        last_activity_at=activity[-1].at,
        now=now,
        has_open_gate=flags.get("gate", False),
        has_open_tool_call=flags.get("tool_call", False),
    )


@pytest.mark.parametrize(
    ("minutes", "status"),
    [(4, SessionStatus.LIVE), (6, SessionStatus.IDLE), (31, SessionStatus.ENDED)],
)
def test_derives_status_from_age_when_last_event_is_minutes_old(
    minutes: float, status: SessionStatus
) -> None:
    assert _status_after(minutes) == status


def test_waits_when_gate_request_open() -> None:
    assert _status_after(6, gate=True) == SessionStatus.WAITING
    assert _status_after(1, gate=True) == SessionStatus.WAITING


def test_stays_live_when_tool_call_has_no_result() -> None:
    assert _status_after(6, tool_call=True) == SessionStatus.LIVE


def test_ends_even_with_open_tool_call_when_silent_for_thirty_minutes() -> None:
    assert _status_after(31, tool_call=True, gate=True) == SessionStatus.ENDED


def test_infers_end_when_no_event_for_thirty_minutes() -> None:
    activity = [_activity(0), _activity(2)]

    segments = session_segments(activity, now=START + timedelta(minutes=33))

    assert len(segments) == 1
    assert segments[0].ended_at == activity[-1].at
    assert segments[0].end_reason == "no_end_event"
    assert segments[0].end_inferred is True


def test_closes_segment_when_session_end_arrives() -> None:
    activity = [_activity(0), _activity(3, ends=True, end_reason="logout", outcome="stopped")]

    segments = session_segments(activity, now=START + timedelta(minutes=4))

    assert segments[0].ended_at == activity[-1].at
    assert segments[0].end_reason == "logout"
    assert segments[0].end_inferred is False


def test_reopens_as_segment_two_when_event_follows_inferred_end() -> None:
    later = START + timedelta(minutes=2) + END_AFTER + timedelta(minutes=5)
    activity = [_activity(0), _activity(2), Activity(at=later)]

    segments = session_segments(activity, now=later + timedelta(minutes=1))
    status = session_status(
        segments,
        last_activity_at=later,
        now=later + timedelta(minutes=1),
        has_open_gate=False,
        has_open_tool_call=False,
    )

    assert [segment.index for segment in segments] == [1, 2]
    assert segments[0].end_inferred is True
    assert segments[1].started_at == later
    assert segments[1].ended_at is None
    assert status == SessionStatus.LIVE


def test_reopens_as_segment_two_when_event_follows_session_end() -> None:
    activity = [_activity(0), _activity(1, ends=True, outcome="done"), _activity(10)]

    segments = session_segments(activity, now=START + timedelta(minutes=11))

    assert [(segment.index, segment.ended_at) for segment in segments] == [
        (1, START + timedelta(minutes=1)),
        (2, None),
    ]


def test_keeps_outcome_value_when_activity_ends() -> None:
    assert _activity(1, ends=True, outcome="done").outcome == Outcome.DONE
