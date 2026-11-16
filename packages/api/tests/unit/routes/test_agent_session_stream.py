import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from agent_hub.api.routes.agent_session_stream import session_stream
from agent_hub.core.agent_sessions.records import StreamItem
from agent_hub.core.testing.read_model_builders import a_log_record

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


class Parked:
    """A subscription that sends one record, then waits for a frame that never comes."""

    def __init__(self) -> None:
        self.cancelled = False
        self.closed = False

    async def frames(self) -> AsyncIterator[StreamItem]:
        try:
            yield a_log_record("text", seq=1)
            await asyncio.Event().wait()
            yield a_log_record("text", seq=2)  # pragma: no cover -- never reached
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.closed = True


async def test_cancels_and_closes_subscription_when_client_leaves_mid_wait() -> None:
    parked = Parked()
    stream = session_stream(parked.frames(), reset=None, last_id=None, now=lambda: NOW)

    sent = [await anext(stream), await anext(stream)]
    waiting = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await stream.aclose()

    assert sent[1].startswith(b"event: record.text\nid: 1\n")
    assert (parked.cancelled, parked.closed) == (True, True)
