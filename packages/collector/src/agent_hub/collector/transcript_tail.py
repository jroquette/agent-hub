"""The live transcript tail (D9, E6): read what a session's transcript gained since last time.

Only a regular file whose real path is under the Claude Code projects folder is read; the last
path component is opened with ``O_NOFOLLOW`` (a symlink is refused, never followed) and
``O_NONBLOCK`` (a FIFO swapped in cannot block), then ``fstat`` must show a regular file. Each
read takes at most ``max_bytes`` and stops at the last complete line, so a line being written is
read next time. A line longer than ``max_line_bytes`` is skipped and counted. Offsets, turns and
the usage message ids seen live in memory per path, the newest ``max_paths`` kept; after a
restart a file is read again from the start and the store's idempotency drops the duplicates.
The events are attributed to the ref's project, repo and agent, as the hook mapper set them.
"""

import os
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.collector.transcript import MAX_LINE_BYTES, TranscriptOrigin, parse_transcript
from agent_hub.core.ingestion.ingestion_ports import TailResult, TranscriptRef

MAX_READ_BYTES: Final = 8 * 1_048_576
MAX_PATHS: Final = 10_000
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_NEWLINE: Final = b"\n"


@dataclass(kw_only=True, slots=True)
class _Progress:
    offset: int = 0
    turn: int = 0
    seen_messages: frozenset[str] = frozenset()
    # Inside a line longer than the limit: drop bytes up to its newline.
    is_skipping: bool = False


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
        self._progress: OrderedDict[str, _Progress] = OrderedDict()
        self._lock = threading.Lock()

    def read_new(self, ref: TranscriptRef) -> TailResult:
        """The events of the lines appended to ``ref.path`` since the last read of it."""
        origin = TranscriptOrigin(
            project=ref.project, repo=ref.repo, agent=ref.agent, session=ref.session
        )
        real = self._allowed_path(ref.path)
        if real is None:
            return TailResult(events=(), refused=True)
        with self._lock:
            return self._read(real, origin)

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
            progress = self._progress_of(real, size=info.st_size)
            chunk = os.pread(descriptor, self._max_bytes, progress.offset)
        except OSError:
            return TailResult(events=(), refused=True)
        finally:
            os.close(descriptor)
        return self._parse(chunk, progress, origin)

    def _progress_of(self, real: str, *, size: int) -> _Progress:
        progress = self._progress.get(real)
        if progress is None or size < progress.offset:
            # New, or truncated and rewritten: read it from the start again.
            progress = _Progress()
        self._progress[real] = progress
        self._progress.move_to_end(real)
        while len(self._progress) > self._max_paths:
            self._progress.popitem(last=False)
        return progress

    def _parse(self, chunk: bytes, progress: _Progress, origin: TranscriptOrigin) -> TailResult:
        skipped = 0
        if progress.is_skipping:
            end = chunk.find(_NEWLINE)
            if end < 0:
                progress.offset += len(chunk)
                return TailResult(events=())
            progress.offset += end + 1
            progress.is_skipping = False
            chunk = chunk[end + 1 :]
        end = chunk.rfind(_NEWLINE)
        if end < 0:
            if len(chunk) >= min(self._max_bytes, self._max_line_bytes):
                # One line fills the read and is still not complete: too long, skip it.
                progress.offset += len(chunk)
                progress.is_skipping = True
                skipped += 1
            return TailResult(events=(), skipped_lines=skipped)
        complete = chunk[: end + 1]
        batch = parse_transcript(
            complete.decode("utf-8", errors="replace"),
            origin=origin,
            start_turn=progress.turn,
            seen_messages=progress.seen_messages,
            max_line_bytes=self._max_line_bytes,
        )
        progress.offset += len(complete)
        progress.turn = batch.end_turn
        progress.seen_messages = batch.seen_messages
        return TailResult(events=batch.events, skipped_lines=skipped + len(batch.problems))
