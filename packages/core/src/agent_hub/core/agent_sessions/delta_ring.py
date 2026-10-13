"""The ring of text deltas of one live session (S4, E8): memory only, at most ``capacity``.

Deltas are never stored: the completed ``text`` record supersedes them. Each delta is keyed by
``after_seq`` (the last persisted record when it came) and ``index``, its position among the
deltas since that record, which the ring numbers itself so that the SSE id
``<after_seq>.<index>`` stays unique even when deltas of several blocks share one
``after_seq``. Keys only grow; when the ring is full the oldest delta goes.

``since(after_seq, index)`` answers the deltas a reconnecting client still needs (those of
``after_seq`` after ``index``), or None when the ring dropped one of them: the client then gets
the completed ``text`` record instead.
"""

from collections import deque

from agent_hub.core.agent_sessions.records import DeltaFrame


class DeltaRing:
    """The newest ``capacity`` text deltas of one session."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            msg = "a delta ring holds at least one delta"
            raise ValueError(msg)
        self._frames: deque[DeltaFrame] = deque(maxlen=capacity)
        self._last: tuple[int, int] | None = None
        self._dropped: tuple[int, int] | None = None

    def push(self, after_seq: int, block: int, text: str) -> DeltaFrame:
        """Keep a delta of ``block`` that came after record ``after_seq``; answers its frame."""
        last = self._last
        if last is not None and after_seq < last[0]:
            msg = f"after_seq {after_seq} is older than the ring's {last[0]}"
            raise ValueError(msg)
        index = last[1] + 1 if last is not None and last[0] == after_seq else 0
        if len(self._frames) == self._frames.maxlen:
            oldest = self._frames[0]
            self._dropped = (oldest.after_seq, oldest.index)
        frame = DeltaFrame(after_seq=after_seq, block=block, index=index, text=text)
        self._frames.append(frame)
        self._last = (after_seq, index)
        return frame

    def since(self, after_seq: int, index: int | None = None) -> list[DeltaFrame] | None:
        """The deltas of ``after_seq`` after ``index`` (all of them when None), in order; None
        when the ring no longer holds them all."""
        first = 0 if index is None else index + 1
        if self._dropped is not None and self._dropped >= (after_seq, first):
            return None
        return [
            frame for frame in self._frames if frame.after_seq == after_seq and frame.index >= first
        ]
