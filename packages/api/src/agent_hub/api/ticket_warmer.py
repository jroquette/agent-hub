"""The ticket warmer of ``hub web``: Linear's ticket cache kept warm while a tab is open (AGH-613).

RED stub for AGH-613 (plan FEAT-1 commit 23a): the names the tests import, with no logic yet.
"""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Final

from agent_hub.api.connected_browsers import ConnectedBrowsers
from agent_hub.api.doctor_refresher import Ticker
from agent_hub.api.ticket_snapshots import MAX_ENTRIES
from agent_hub.core.features.ticket_snapshots import SnapshotRequest, TicketSnapshots

WARM_SECONDS: Final = 30.0
REFRESH_AGE: Final = timedelta(minutes=14)
WARM_LIMIT: Final = MAX_ENTRIES - 32
UNAUTHORIZED_PAUSE: Final = timedelta(minutes=15)


class TicketWarmer:
    def __init__(
        self,
        requests: Callable[[], Sequence[SnapshotRequest]],
        snapshots: TicketSnapshots,
        browsers: ConnectedBrowsers,
        *,
        ticker: Ticker,
        key_digest: Callable[[], str | None],
        clock: Callable[[], datetime],
    ) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        raise NotImplementedError

    def begin_exit(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError
