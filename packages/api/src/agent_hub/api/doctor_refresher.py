"""The background part of ``hub web`` that keeps each hub's facts and last check fresh (AGH-608).

RED stub for AGH-608 (plan DOC-2 commit 16a): the names the tests import, with no logic yet.
"""

import threading
from collections.abc import Callable
from typing import Final, Protocol

from agent_hub.core.hubs.hub_snapshot import RefreshReport

POLL_SECONDS: Final = 2.0


class Ticker(Protocol):
    def start(self, tick: Callable[[], None]) -> None: ...

    def stop(self) -> None: ...


class DaemonTicker:
    def __init__(self, interval: float, *, name: str) -> None:
        raise NotImplementedError

    @property
    def thread(self) -> threading.Thread:
        raise NotImplementedError

    def start(self, tick: Callable[[], None]) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class RefreshedHubs(Protocol):
    def reread_hubs(self, written: str | None = None) -> None: ...

    def refresh(self) -> RefreshReport: ...


class DoctorRefresher:
    def __init__(self, hubs: RefreshedHubs, *, ticker: Ticker) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        raise NotImplementedError

    def begin_exit(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError
