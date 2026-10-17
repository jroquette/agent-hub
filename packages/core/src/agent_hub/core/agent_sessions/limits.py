"""The bounds of agent sessions (L3, P14): ``hub web`` options build one ``SessionLimits``.

The ranges are the options' (P14); the last six are fixed by the plan and only tests change
them.
"""

from datetime import timedelta

from pydantic import Field

from agent_hub.core.readmodels.view_types import ViewModel

KIB = 1024
MIB = 1024 * KIB


class SessionLimits(ViewModel):
    """How many live sessions, how long they wait, how much each one logs."""

    sessions_max: int = Field(default=4, ge=1, le=16)
    idle_seconds: int = Field(default=1800, ge=1, le=86_400)
    permission_timeout_seconds: int = Field(default=600, ge=1, le=86_400)
    log_records: int = Field(default=50_000, ge=100, le=1_000_000)
    log_bytes: int = Field(default=32 * MIB, ge=64 * KIB, le=1024 * MIB)
    message_max_bytes: int = Field(default=1 * MIB, ge=KIB, le=4 * MIB)
    cloud_timeout_seconds: int = Field(default=60, ge=5, le=600)
    retention_days: int = Field(default=30, ge=1, le=3650)
    delta_ring: int = Field(default=2000, ge=1)
    subscribers: int = Field(default=8, ge=1)
    tool_result_bytes: int = Field(default=64 * KIB, ge=1)
    summary_bytes: int = Field(default=4 * KIB, ge=1)
    error_bytes: int = Field(default=2 * KIB, ge=1)
    headroom: int = Field(default=16, ge=0)

    @property
    def idle(self) -> timedelta:
        """How long a session may stay idle before it ends ``idle_timeout``."""
        return timedelta(seconds=self.idle_seconds)

    @property
    def permission_timeout(self) -> timedelta:
        """How long a permission request waits before it is denied ``by: timeout``."""
        return timedelta(seconds=self.permission_timeout_seconds)

    @property
    def retention(self) -> timedelta:
        """How long an ended session's log is kept."""
        return timedelta(days=self.retention_days)
