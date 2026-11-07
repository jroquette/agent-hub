"""``hub web``'s import of the hook sensor's spool when it starts (AGH-699).

``SpoolImport`` is an ``AppLifecycle`` part. ``start`` takes the spool (the collector's
``HookSpool``) and sends its envelopes through ``IngestHook``, the live hook route's own path, so
the same redaction and transcript tail apply and a replayed envelope is a duplicate. It runs once,
on the starting thread, before the first request, so it stores the envelopes in batches of at most
``batch_size`` (one transaction each, ``IngestHook.execute_all``) and logs their number first. A
bad line is skipped; a batch that fails other than in the store (an envelope that conflicts with
stored events, or one the hook path fails on) is sent again one envelope at a time, each
transcript read to its end as in a batch, skipping and counting each envelope that conflicts or
fails; then the taken file is removed. A spool that cannot be read, or a store that fails
(``StorageError``), is logged with the error's type only and leaves the taken file for the next
start: the app starts either way. Logs never quote the spool's text.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from agent_hub.collector.hook_spool import HookSpool
from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.hook_envelope import HookEnvelope
from agent_hub.core.ingestion.ingest_hook import IngestHook
from agent_hub.storage.errors import StorageError

# Envelopes per transaction: a full spool (about 8,000 lines) in a few seconds, not one commit each.
SPOOL_BATCH: Final = 500

_log = logging.getLogger(__name__)


@dataclass(kw_only=True, slots=True)
class _Tally:
    """What an import stored and skipped so far."""

    appended: int = 0
    duplicates: int = 0
    conflicts: int = 0
    failed: int = 0

    def add(self, result: AppendResult) -> None:
        self.appended += result.appended
        self.duplicates += result.duplicates


class SpoolImport:
    """The spool's import at start (see the module docstring)."""

    def __init__(
        self, spool: HookSpool, ingest: IngestHook, *, batch_size: int = SPOOL_BATCH
    ) -> None:
        self._spool = spool
        self._ingest = ingest
        self._batch_size = batch_size

    async def start(self) -> None:
        """Import the spool; never raises."""
        try:
            self._import()
        except Exception as error:  # noqa: BLE001 -- logged; the taken file waits for the next start
            _log.warning("hook spool import failed", extra={"error_type": type(error).__name__})

    def begin_exit(self) -> None:
        """Nothing to begin: the import ended at start."""

    async def stop(self) -> None:
        """Nothing to stop: the import ended at start."""

    def _import(self) -> None:
        taken = self._spool.take()
        if taken is None:
            return
        envelopes = [item.envelope for item in taken.lines.envelopes]
        # Counts only, in the message: the JSON formatter writes no other field of them.
        _log.info(
            "hook spool import started: %d envelopes, %d bad lines",
            len(envelopes),
            len(taken.lines.errors),
        )
        tally = _Tally()
        for first in range(0, len(envelopes), self._batch_size):
            self._store(envelopes[first : first + self._batch_size], tally)
        self._spool.remove(taken)
        _log.info(
            "hook spool imported: appended %d, duplicates %d, conflicts %d, failed %d, "
            "bad lines %d, dropped by the sensor %d",
            tally.appended,
            tally.duplicates,
            tally.conflicts,
            tally.failed,
            len(taken.lines.errors),
            taken.lines.dropped,
        )

    def _store(self, batch: Sequence[HookEnvelope], tally: _Tally) -> None:
        """``batch`` stored in one transaction, else one envelope at a time."""
        try:
            tally.add(self._ingest.execute_all(batch))
        except StorageError:
            raise
        except Exception:  # noqa: BLE001 -- a conflict or one failing envelope: one at a time
            self._store_each(batch, tally)

    def _store_each(self, batch: Sequence[HookEnvelope], tally: _Tally) -> None:
        """Each envelope of ``batch`` stored on its own, its transcript read to its end; one that
        conflicts or fails other than in the store is skipped and counted."""
        for envelope in batch:
            try:
                tally.add(self._ingest.execute(envelope, is_to_end=True))
            except StorageError:
                raise
            except EventConflictError:
                tally.conflicts += 1
            except Exception as error:  # noqa: BLE001 -- skipped and counted; the rest goes on
                tally.failed += 1
                _log.warning(
                    "hook spool envelope skipped", extra={"error_type": type(error).__name__}
                )
