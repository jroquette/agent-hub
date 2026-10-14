from datetime import timedelta

import pytest
from pydantic import ValidationError

from agent_hub.core.agent_sessions.limits import SessionLimits


def test_defaults_match_lead_answers_when_built() -> None:
    limits = SessionLimits()

    assert limits.sessions_max == 4
    assert limits.idle_seconds == 1800
    assert limits.permission_timeout_seconds == 600
    assert limits.log_records == 50_000
    assert limits.log_bytes == 32 * 1024 * 1024
    assert limits.message_max_bytes == 64 * 1024
    assert limits.cloud_timeout_seconds == 60
    assert limits.retention_days == 30
    assert (limits.delta_ring, limits.subscribers, limits.headroom) == (2000, 8, 16)
    assert (limits.tool_result_bytes, limits.summary_bytes, limits.error_bytes) == (
        65_536,
        4096,
        2048,
    )


def test_gives_durations_when_asked() -> None:
    limits = SessionLimits(idle_seconds=2, permission_timeout_seconds=1, retention_days=30)

    assert limits.idle == timedelta(seconds=2)
    assert limits.permission_timeout == timedelta(seconds=1)
    assert limits.retention == timedelta(days=30)


@pytest.mark.parametrize(
    "field", [{"sessions_max": 0}, {"sessions_max": 17}, {"log_records": 99}, {"log_bytes": 1}]
)
def test_refuses_limit_when_out_of_range(field: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        SessionLimits.model_validate(field)


def test_accepts_low_caps_when_test_configures_them() -> None:
    limits = SessionLimits(sessions_max=2, log_records=100, log_bytes=65_536)

    assert (limits.sessions_max, limits.log_records, limits.log_bytes) == (2, 100, 65_536)
