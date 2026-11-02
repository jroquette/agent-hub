"""The count of the browser tabs that hold the global event stream open (AGH-613).

RED stub for AGH-613 (plan FEAT-1): the names the tests import, with no logic yet.
"""

from collections.abc import AsyncIterator, Callable


class ConnectedBrowsers:
    def __init__(self, on_first_open: Callable[[], None] | None = None) -> None:
        raise NotImplementedError

    def opened(self) -> None:
        raise NotImplementedError

    def closed(self) -> None:
        raise NotImplementedError

    def connected(self) -> bool:
        raise NotImplementedError


def counted(stream: AsyncIterator[bytes], browsers: ConnectedBrowsers) -> AsyncIterator[bytes]:
    raise NotImplementedError
