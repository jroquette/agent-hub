"""What ``hub web`` passes to the API: where the store and the hub registry are, the port."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agent_hub.core.agent_sessions.limits import SessionLimits

DEFAULT_PORT = 7420


def utc_now() -> datetime:
    """The current time, aware and in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class ApiSettings:
    """The API's settings; ``running_version`` is the ``hub`` that serves it, ``clock`` the time
    source every derivation's ``now`` comes from (injected in tests), ``allowed_hosts`` the exact
    ``host:port`` names answered besides the loopback ones (``AGENT_HUB_ALLOWED_HOSTS``).

    ``session_token`` is this launch's token for the agent-session routes (None: every such
    route answers 401; hidden from ``repr`` so it never reaches a log), ``sessions_off`` turns
    those routes off (404, the container, L2) and ``limits`` bounds the sessions (P14).
    ``bound_host`` is the address the socket listens on, so the sessions' children reach this
    server where it really listens (``AGENT_HUB_WEB_URL``)."""

    db_path: Path
    registry_path: Path
    port: int
    running_version: str
    clock: Callable[[], datetime] = field(default=utc_now)
    allowed_hosts: frozenset[str] = frozenset()
    session_token: str | None = field(default=None, repr=False)
    sessions_off: bool = False
    limits: SessionLimits = field(default_factory=SessionLimits)
    bound_host: str = "127.0.0.1"
