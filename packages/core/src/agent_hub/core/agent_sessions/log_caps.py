"""The caps of one session's log (L3, E12): records, stored text, tool result size.

``LogBudget`` counts what a session has logged and admits each record before it is stored:

- a ``tool.result`` whose content is over ``tool_result_bytes`` is stored clipped, with
  ``truncated: true`` and the content's ``original_bytes`` (``Truncated``); structured content
  is clipped as its JSON text;
- an ordinary record is refused (``Full``) once the log holds ``log_records - headroom``
  records or would pass ``log_bytes`` of text; from then on every ordinary record is refused;
- a ``reserved`` record (the audit and terminal records written while the session ends
  ``log_full``: ``log.truncated``, ``interrupt``, decisions ``by: closed``, ``result``,
  ``exited``, ``close``) uses the headroom and is refused only past ``log_records``.

Pass the stored copy (``record_text.redacted``): clipping comes after redaction. The budget is
a counter in memory, one per live session, with no I/O.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.record_text import clip_bytes, compact_json, text_bytes
from agent_hub.core.agent_sessions.records import LogRecord


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Admitted(_Frozen):
    """Store ``record`` as it is."""

    record: LogRecord


class Truncated(_Frozen):
    """Store ``record``, whose tool result was clipped from ``original_bytes``."""

    record: LogRecord
    original_bytes: int


class Full(_Frozen):
    """The log reached ``cap`` (whose value is ``limit``): the record is not stored, and the
    session ends ``log_full``."""

    cap: Literal["records", "bytes"]
    limit: int


type Admission = Admitted | Truncated | Full


class LogBudget:
    """What one session's log holds, and whether the next record fits."""

    def __init__(self, limits: SessionLimits, *, records: int = 0, stored_bytes: int = 0) -> None:
        self._limits = limits
        self._records = records
        self._stored_bytes = stored_bytes
        self._full = False

    @property
    def records(self) -> int:
        """How many records the log holds."""
        return self._records

    @property
    def stored_bytes(self) -> int:
        """How many bytes of text the log holds."""
        return self._stored_bytes

    @property
    def full(self) -> bool:
        """Whether a cap was reached: only reserved records are admitted now."""
        return self._full

    def admit(self, record: LogRecord, *, reserved: bool = False) -> Admission:
        """Count ``record`` in and say how to store it, or refuse it (``Full``); the admitted
        record's ``text_bytes`` is its body's size, counted here."""
        size = text_bytes(record.body)
        if record.text_bytes != size:
            record = record.model_copy(update={"text_bytes": size})
        admission: Admitted | Truncated = Admitted(record=record)
        if record.kind == "tool.result":
            admission = self._clipped(record)
        stored = admission.record
        refused = self._refusal(stored, reserved=reserved)
        if refused is not None:
            return refused
        self._records += 1
        self._stored_bytes += stored.text_bytes
        return admission

    def _refusal(self, record: LogRecord, *, reserved: bool) -> Full | None:
        limits = self._limits
        if reserved:
            if self._records + 1 > limits.log_records:
                return Full(cap="records", limit=limits.log_records)
            return None
        if self._full or self._records + 1 > limits.log_records - limits.headroom:
            self._full = True
            return Full(cap="records", limit=limits.log_records)
        if self._stored_bytes + record.text_bytes > limits.log_bytes:
            self._full = True
            return Full(cap="bytes", limit=limits.log_bytes)
        return None

    def _clipped(self, record: LogRecord) -> Admitted | Truncated:
        content = record.body.get("content")
        text = content if isinstance(content, str) else compact_json(content)
        size = len(text.encode())
        limit = self._limits.tool_result_bytes
        if size <= limit:
            return Admitted(record=record)
        body: dict[str, JsonValue] = record.body | {
            "content": clip_bytes(text, limit),
            "truncated": True,
            "original_bytes": size,
        }
        clipped = record.model_copy(update={"body": body, "text_bytes": text_bytes(body)})
        return Truncated(record=clipped, original_bytes=size)
