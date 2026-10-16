"""The live transcript tail (D9, E6): read what a session's transcript gained since last time.

Only a regular file whose real path is under the Claude Code projects folder is read; the last
path component is opened with ``O_NOFOLLOW`` (a symlink is refused, never followed) and
``O_NONBLOCK`` (a FIFO swapped in cannot block), then ``fstat`` must show a regular file. Each
read takes at most ``max_bytes`` and stops at the last complete line, so a line being written is
read next time. A line longer than ``max_line_bytes`` is skipped and counted. Offsets, turns, the
usage message ids and titles seen and the last line's timestamp live in memory per path, the
newest ``max_paths`` kept; after a restart a file is read again from the start and the store's
idempotency drops the duplicates.
A read is two-phase: it leaves the progress as it was and returns a position; ``commit`` moves
the progress there once the events are stored, so a failed append loses no line. Only the
newest read of a path can be committed; an older position is ignored.
The events are attributed to the ref's project, repo and agent, as the hook mapper set them.
"""

import os
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Final

from agent_hub.collector.transcript import MAX_LINE_BYTES, TranscriptOrigin, parse_transcript
from agent_hub.core.events.event import Event
from agent_hub.core.ingestion.ingestion_ports import TailPosition, TailResult, TranscriptRef

MAX_READ_BYTES: Final = 8 * 1_048_576
MAX_PATHS: Final = 10_000
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_NEWLINE: Final = b"\n"


@dataclass(frozen=True, kw_only=True, slots=True)
class _Progress:
    offset: int = 0
    turn: int = 0
    seen_messages: frozenset[str] = frozenset()
    seen_titles: frozenset[str] = frozenset()
    last_timestamp: datetime | None = None
    # Inside a line longer than the limit: drop bytes up to its newline.
    is_skipping: bool = False


@dataclass(kw_only=True, slots=True)
class _PathState:
    committed: _Progress
    # The newest read's end, waiting for its commit: (version, progress).
    pending: tuple[int, _Progress] | None = None


class TranscriptTail:
    """``TranscriptTailer`` over the files under ``projects_root`` (``~/.claude/projects``)."""

    def __init__(
        self,
        projects_root: Path,
        *,
        max_bytes: int = MAX_READ_BYTES,
        max_line_bytes: int = MAX_LINE_BYTES,
        max_paths: int = MAX_PATHS,
    ) -> None:
        self._root = projects_root
        self._max_bytes = max_bytes
        self._max_line_bytes = max_line_bytes
        self._max_paths = max_paths
        self._states: OrderedDict[str, _PathState] = OrderedDict()
        self._versions = 0
        self._lock = threading.Lock()

    def read_new(self, ref: TranscriptRef) -> TailResult:
        """The events of the lines appended to ``ref.path`` since the last committed read."""
        origin = TranscriptOrigin(
            project=ref.project, repo=ref.repo, agent=ref.agent, session=ref.session
        )
        real = self._allowed_path(ref.path)
        if real is None:
            return TailResult(events=(), refused=True)
        with self._lock:
            return self._read(real, origin)

    def commit(self, position: TailPosition) -> None:
        """Move the progress of ``position.path`` to the read it names, if it is the newest."""
        with self._lock:
            state = self._states.get(position.path)
            if state is None or state.pending is None or state.pending[0] != position.version:
                return
            state.committed = state.pending[1]
            state.pending = None

    def _allowed_path(self, path: str) -> str | None:
        # The folders are resolved; the file itself is opened with O_NOFOLLOW, so a link there
        # is refused instead of followed.
        name = os.path.basename(path)
        if not os.path.isabs(path) or name in {"", ".", ".."}:
            return None
        root = os.path.realpath(self._root)
        real = os.path.join(os.path.realpath(os.path.dirname(path)), name)
        if os.path.commonpath([root, real]) != root:
            return None
        return real

    def _read(self, real: str, origin: TranscriptOrigin) -> TailResult:
        try:
            descriptor = os.open(real, _OPEN_FLAGS)
        except OSError:
            return TailResult(events=(), refused=True)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                return TailResult(events=(), refused=True)
            state = self._state_of(real, size=info.st_size)
            chunk = os.pread(descriptor, self._max_bytes, state.committed.offset)
        except OSError:
            return TailResult(events=(), refused=True)
        finally:
            os.close(descriptor)
        events, skipped, reached = self._parse(chunk, state.committed, origin)
        self._versions += 1
        state.pending = (self._versions, reached)
        position = TailPosition(path=real, version=self._versions)
        return TailResult(events=events, skipped_lines=skipped, position=position)

    def _state_of(self, real: str, *, size: int) -> _PathState:
        state = self._states.get(real)
        if state is None or size < state.committed.offset:
            # New, or truncated and rewritten: read it from the start again.
            state = _PathState(committed=_Progress())
        self._states[real] = state
        self._states.move_to_end(real)
        while len(self._states) > self._max_paths:
            self._states.popitem(last=False)
        return state

    def _parse(
        self, chunk: bytes, progress: _Progress, origin: TranscriptOrigin
    ) -> tuple[tuple[Event, ...], int, _Progress]:
        """The events of ``chunk``'s complete lines, the lines skipped and the progress reached."""
        skipped = 0
        if progress.is_skipping:
            end = chunk.find(_NEWLINE)
            if end < 0:
                return (), 0, replace(progress, offset=progress.offset + len(chunk))
            progress = replace(progress, offset=progress.offset + end + 1, is_skipping=False)
            chunk = chunk[end + 1 :]
        end = chunk.rfind(_NEWLINE)
        if end < 0:
            if len(chunk) >= min(self._max_bytes, self._max_line_bytes):
                # One line fills the read and is still not complete: too long, skip it.
                progress = replace(progress, offset=progress.offset + len(chunk), is_skipping=True)
                skipped += 1
            return (), skipped, progress
        complete = chunk[: end + 1]
        batch = parse_transcript(
            complete.decode("utf-8", errors="replace"),
            origin=origin,
            start_turn=progress.turn,
            seen_messages=progress.seen_messages,
            seen_titles=progress.seen_titles,
            last_timestamp=progress.last_timestamp,
            max_line_bytes=self._max_line_bytes,
        )
        reached = replace(
            progress,
            offset=progress.offset + len(complete),
            turn=batch.end_turn,
            seen_messages=batch.seen_messages,
            seen_titles=batch.seen_titles,
            last_timestamp=batch.last_timestamp,
        )
        return batch.events, skipped + len(batch.problems), reached
