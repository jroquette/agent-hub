"""What ``hub web`` passes to the API: where the store and the hub registry are, the port."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_PORT = 7420


def utc_now() -> datetime:
    """The current time, aware and in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class ApiSettings:
    """The API's settings; ``running_version`` is the ``hub`` that serves it, ``clock`` the time
    source every derivation's ``now`` comes from (injected in tests), ``allowed_hosts`` the exact
    ``host:port`` names answered besides the loopback ones (``AGENT_HUB_ALLOWED_HOSTS``)."""

    db_path: Path
    registry_path: Path
    port: int
    running_version: str
    clock: Callable[[], datetime] = field(default=utc_now)
    allowed_hosts: frozenset[str] = frozenset()
