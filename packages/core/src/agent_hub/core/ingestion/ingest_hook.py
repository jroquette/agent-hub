"""Ingest one hook envelope: map it to events, append them, then read the transcript it names."""

from collections.abc import Sequence

from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult, EventStore
from agent_hub.core.ingestion.hook_envelope import HookEnvelope
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.ingestion.ingestion_ports import HookMapper, TailPosition, TranscriptTailer
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

    def execute(self, envelope: HookEnvelope, *, is_to_end: bool = False) -> AppendResult:
        """Append what ``envelope`` yields; the result adds the hook's and the transcript's counts.

        ``is_to_end`` reads the transcript to its end (``read_to_end``, as a spool import does)
        instead of its next piece. An ``EventConflictError`` propagates (nothing of that batch is
        written).
        """
        self._status.record_hook()
        mapping = self._mapper.map(envelope)
        result = self._append(mapping.events)
        if mapping.transcript is None:
            return result
        read = self._tailer.read_to_end if is_to_end else self._tailer.read_new
        tail = read(mapping.transcript)
        self._status.record_tail(refused=tail.refused, skipped_lines=tail.skipped_lines)
        tail_result = self._append(tail.events)
        if tail.position is not None:
            self._tailer.commit(tail.position)
        return AppendResult(
            appended=result.appended + tail_result.appended,
            duplicates=result.duplicates + tail_result.duplicates,
        )

    def execute_all(self, envelopes: Sequence[HookEnvelope]) -> AppendResult:
        """Append what every envelope yields as one batch, all or nothing (a spool import).

        Each envelope is mapped in order, and a transcript is read right after the first envelope
        that names it, once and to its end within the tailer's budget (``read_to_end``), with that
        envelope's attribution; the batch holds the hooks' events and the transcripts' in that
        order. The tail positions are committed only once the batch is stored, so a transcript
        past the budget is read on from there by its next read. An ``EventConflictError``
        propagates with nothing written and no position committed.
        """
        events: list[Event] = []
        positions: list[TailPosition] = []
        read: set[str] = set()
        for envelope in envelopes:
            self._status.record_hook()
            mapping = self._mapper.map(envelope)
            events.extend(mapping.events)
            if mapping.transcript is None or mapping.transcript.path in read:
                continue
            read.add(mapping.transcript.path)
            tail = self._tailer.read_to_end(mapping.transcript)
            self._status.record_tail(refused=tail.refused, skipped_lines=tail.skipped_lines)
            events.extend(tail.events)
            if tail.position is not None:
                positions.append(tail.position)
        result = self._append(tuple(events))
        for position in positions:
            self._tailer.commit(position)
        return result

    def _append(self, events: tuple[Event, ...]) -> AppendResult:
        if not events:
            return AppendResult(appended=0, duplicates=0)
        result = self._ingest.execute(events)
        self._status.record_append(result, sources={event.source for event in events})
        return result
