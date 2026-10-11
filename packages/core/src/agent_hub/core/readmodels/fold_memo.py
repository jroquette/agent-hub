"""An in-process memo of folds, keyed by the store's high-water mark (D12).

A fold is recomputed only when the store has grown since it was computed; nothing is written
to disk, and a restart starts empty. The least recently used keys are dropped past
``max_entries``. Safe to share between the API's worker threads.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable

DEFAULT_MAX_ENTRIES = 256


class FoldMemo[K: Hashable, V]:
    """Values per key, each valid for the high-water mark it was computed at."""

    def __init__(self, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[K, tuple[int, V]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: K, *, hwm: int, compute: Callable[[], V]) -> V:
        """The value of ``key`` at ``hwm``: the memoized one, or ``compute()`` stored anew."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] == hwm:
                self._entries.move_to_end(key)
                return entry[1]
        value = compute()
        with self._lock:
            self._entries[key] = (hwm, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return value
