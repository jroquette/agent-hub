"""Each registered hub's facts and last doctor check, kept off the request (AGH-608).

RED stub for AGH-608 (plan DOC-1 commit 14a): the names the tests import, with no logic yet.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.snapshot import LockState
from agent_hub.core.hubs.doctor_cache import DOCTOR_TTL
from agent_hub.core.hubs.hub_document import HubDocument
from agent_hub.core.hubs.hub_registry import HubFileReader, HubRegistry
from agent_hub.core.hubs.list_hubs import HubRead

MIN_RUN_INTERVAL: Final = timedelta(seconds=10)


@dataclass(frozen=True, kw_only=True, slots=True)
class HubCheck:
    findings: tuple[Finding, ...]
    checked_at: datetime


@dataclass(frozen=True, kw_only=True, slots=True)
class HubState:
    read: HubRead
    lock: LockState | None
    check: HubCheck | None


@dataclass(frozen=True, kw_only=True, slots=True)
class RefreshFailure:
    hub_path: str
    error: Exception


@dataclass(frozen=True, kw_only=True, slots=True)
class RefreshReport:
    checked: tuple[str, ...]
    failures: tuple[RefreshFailure, ...]


class HubSnapshot:
    def __init__(
        self,
        registry: HubRegistry,
        reader: HubFileReader,
        *,
        running_version: str,
        clock: Callable[[], datetime],
        ttl: timedelta = DOCTOR_TTL,
        min_interval: timedelta = MIN_RUN_INTERVAL,
    ) -> None:
        raise NotImplementedError

    def hubs(self) -> tuple[HubState, ...]:
        raise NotImplementedError

    def reread(self, written: str | None = None) -> None:
        raise NotImplementedError

    def refresh(self) -> RefreshReport:
        raise NotImplementedError

    def drift_of(self, hub_path: str, document: HubDocument) -> bool | None:
        raise NotImplementedError
