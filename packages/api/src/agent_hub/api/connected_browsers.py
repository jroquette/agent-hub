"""The count of the browser tabs that hold the global event stream open (AGH-613).

The app shell keeps one ``GET /api/v1/events/stream`` open in every tab that shows the app, so
the number of those streams open is the number of tabs: the ticket warmer reads Linear only
while it is above 0 (``connected()``), and the first tab to open wakes it (``on_first_open``).
Only that route wraps its bytes with ``counted``; the other streams (a session, the live tiles, a
run) count nothing, since a page holds them beside the global one.

The count is thread-safe and never goes below 0. ``counted`` counts its stream from the first
chunk until the stream ends, fails or is closed (the client left), and then closes the inner
stream, so a stream that errors does not leave the count stuck.
"""

import threading
from collections.abc import AsyncGenerator, Callable


class ConnectedBrowsers:
    """How many global streams are open now; ``on_first_open`` runs when it goes from 0 to 1."""

    def __init__(self, on_first_open: Callable[[], None] | None = None) -> None:
        self._on_first_open = on_first_open
        self._lock = threading.Lock()
        self._open = 0

    def opened(self) -> None:
        """One more global stream is open."""
        with self._lock:
            self._open += 1
            first = self._open == 1
        # Outside the lock: the hook (the warm ticker's wake) never runs under the count's lock.
        if first and self._on_first_open is not None:
            self._on_first_open()

    def closed(self) -> None:
        """One global stream less is open; the count never goes below 0."""
        with self._lock:
            self._open = max(0, self._open - 1)

    def connected(self) -> bool:
        """Whether any global stream is open now."""
        with self._lock:
            return self._open > 0


async def counted(
    stream: AsyncGenerator[bytes], browsers: ConnectedBrowsers
) -> AsyncGenerator[bytes]:
    """``stream``'s chunks, counted as one open global stream from the first chunk until it
    ends, fails or is closed; the inner stream is closed then too."""
    browsers.opened()
    try:
        async for chunk in stream:
            yield chunk
    finally:
        browsers.closed()
        await stream.aclose()
