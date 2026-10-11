"""Ingest one hook envelope: map it to events, append them, then read the transcript it names."""

from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult, EventStore
from agent_hub.core.ingestion.hook_envelope import HookEnvelope
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.ingestion.ingestion_ports import HookMapper, TranscriptTailer
from agent_hub.core.ingestion.ingestion_status import IngestionCounters


class IngestHook:
    """``POST /events/hooks``: one envelope in, its events (and its transcript's new lines) stored.

    Every append goes through ``IngestEvents``, so redaction applies to hooks and transcripts
    alike. A Stop, SubagentStop or SessionEnd hook names a transcript; its new lines are read
    after the hook's own events are stored, so a refused or empty read never loses them. The
    tail's position is committed only after its events are stored: a failed append leaves the
    offset where it was, and the next read returns the same lines.
    """

    def __init__(
        self,
        store: EventStore,
        mapper: HookMapper,
        tailer: TranscriptTailer,
        *,
        status: IngestionCounters,
    ) -> None:
        self._ingest = IngestEvents(store)
        self._mapper = mapper
        self._tailer = tailer
        self._status = status

    def execute(self, envelope: HookEnvelope) -> AppendResult:
        """Append what ``envelope`` yields; the result adds the hook's and the transcript's counts.

        An ``EventConflictError`` propagates (nothing of that batch is written).
        """
        self._status.record_hook()
        mapping = self._mapper.map(envelope)
        result = self._append(mapping.events)
        if mapping.transcript is None:
            return result
        tail = self._tailer.read_new(mapping.transcript)
        self._status.record_tail(refused=tail.refused, skipped_lines=tail.skipped_lines)
        tail_result = self._append(tail.events)
        if tail.position is not None:
            self._tailer.commit(tail.position)
        return AppendResult(
            appended=result.appended + tail_result.appended,
            duplicates=result.duplicates + tail_result.duplicates,
        )

    def _append(self, events: tuple[Event, ...]) -> AppendResult:
        if not events:
            return AppendResult(appended=0, duplicates=0)
        result = self._ingest.execute(events)
        self._status.record_append(result, sources={event.source for event in events})
        return result
