"""The collector's own status: counters since start, sources' freshness, the redaction rules."""

import threading
from collections.abc import Callable, Collection
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from agent_hub.core.events.event import EventSource
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel

# The version of the redaction rule set (D10); a change is a release note.
REDACTION_RULESET = "r1"


class SourceStatus(ViewModel):
    """When a source last sent an event, and whether that is recent enough."""

    source: EventSource
    last_event_at: ApiTimestamp | None
    state: Literal["fresh", "stale", "never"]


class CollectorStatus(ViewModel):
    """``GET /collector/status``: what ``hub web`` received and stored since it started."""

    state: Literal["running"] = "running"
    db_path: str
    running_version: str
    started_at: ApiTimestamp
    events_total: int = Field(ge=0)
    hooks_received: int = Field(ge=0)
    appended: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    transcript_refused: int = Field(ge=0)
    transcript_lines_skipped: int = Field(ge=0)
    last_event_at: ApiTimestamp | None
    sources: tuple[SourceStatus, ...]
    redaction_ruleset: str = REDACTION_RULESET


# Past these, a source that sent events is "stale" (design spec 02, "Freshness and as of").
SOURCE_STALE_AFTER: dict[EventSource, timedelta] = {
    EventSource.CLAUDE_CODE: timedelta(seconds=60),
    EventSource.TRANSCRIPT: timedelta(minutes=5),
    EventSource.EXECUTOR: timedelta(seconds=60),
}


class IngestionCounters:
    """The collector's counters since ``hub web`` started; thread-safe (routes run in threads).

    Only what this process ingests is counted: events other processes append (``hub collect``,
    ``hub run``) reach the store directly and show in ``events_total`` only.
    """

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._started_at = clock()
        self._hooks_received = 0
        self._appended = 0
        self._duplicates = 0
        self._transcript_refused = 0
        self._transcript_lines_skipped = 0
        self._last_event_at: datetime | None = None
        self._source_times: dict[EventSource, datetime] = {}

    def record_hook(self) -> None:
        """One hook envelope was received."""
        with self._lock:
            self._hooks_received += 1

    def record_append(self, result: AppendResult, *, sources: Collection[EventSource]) -> None:
        """An append of events from ``sources`` wrote and skipped what ``result`` says."""
        now = self._clock()
        with self._lock:
            self._appended += result.appended
            self._duplicates += result.duplicates
            if result.appended:
                self._last_event_at = now
                for source in sources:
                    self._source_times[source] = now

    def record_tail(self, *, refused: bool, skipped_lines: int) -> None:
        """A transcript read was refused, or skipped lines over the bounds."""
        with self._lock:
            self._transcript_refused += int(refused)
            self._transcript_lines_skipped += skipped_lines

    def source_times(self) -> dict[str, datetime]:
        """When each source last added an event, for sources that did."""
        with self._lock:
            return {source.value: at for source, at in self._source_times.items()}

    def snapshot(self, *, db_path: str, running_version: str, events_total: int) -> CollectorStatus:
        """The counters as ``GET /collector/status`` shows them."""
        now = self._clock()
        with self._lock:
            sources = tuple(
                _source_status(source, self._source_times.get(source), now=now, stale_after=limit)
                for source, limit in SOURCE_STALE_AFTER.items()
            )
            return CollectorStatus(
                db_path=db_path,
                running_version=running_version,
                started_at=self._started_at,
                events_total=events_total,
                hooks_received=self._hooks_received,
                appended=self._appended,
                duplicates=self._duplicates,
                transcript_refused=self._transcript_refused,
                transcript_lines_skipped=self._transcript_lines_skipped,
                last_event_at=self._last_event_at,
                sources=sources,
            )


def _source_status(
    source: EventSource, last_event_at: datetime | None, *, now: datetime, stale_after: timedelta
) -> SourceStatus:
    if last_event_at is None:
        return SourceStatus(source=source, last_event_at=None, state="never")
    state: Literal["fresh", "stale"] = "stale" if now - last_event_at > stale_after else "fresh"
    return SourceStatus(source=source, last_event_at=last_event_at, state=state)
