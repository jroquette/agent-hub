"""``hub web``'s import of the hook sensor's spool when it starts (AGH-699).

``SpoolImport`` is an ``AppLifecycle`` part. ``start`` takes the spool (the collector's
``HookSpool``) and sends each envelope through ``IngestHook``, the live hook route's own path, so
the same redaction and transcript tail apply and a replayed envelope is a duplicate. It runs once,
on the starting thread, before the first request. A bad line is skipped, as is an envelope whose
events differ from stored ones (a conflict); then the taken file is removed. A spool that cannot
be read, or a store that fails, is logged with the error's type only and leaves the taken file for
the next start: the app starts either way. Logs never quote the spool's text.
"""

import logging

from agent_hub.collector.hook_spool import HookSpool
from agent_hub.core.errors import EventConflictError
from agent_hub.core.ingestion.ingest_hook import IngestHook

_log = logging.getLogger(__name__)


class SpoolImport:
    """The spool's import at start (see the module docstring)."""

    def __init__(self, spool: HookSpool, ingest: IngestHook) -> None:
        self._spool = spool
        self._ingest = ingest

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
        appended = duplicates = conflicts = 0
        for item in taken.lines.envelopes:
            try:
                result = self._ingest.execute(item.envelope)
            except EventConflictError:
                conflicts += 1
                continue
            appended += result.appended
            duplicates += result.duplicates
        self._spool.remove(taken)
        # Counts only, in the message: the JSON formatter writes no other field of them.
        _log.info(
            "hook spool imported: appended %d, duplicates %d, conflicts %d, bad lines %d, "
            "dropped by the sensor %d",
            appended,
            duplicates,
            conflicts,
            len(taken.lines.errors),
            taken.lines.dropped,
        )
