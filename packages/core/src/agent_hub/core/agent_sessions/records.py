"""The agent-session log: one ordered record per driver event plus the audit records (S4).

``seq`` is gap-free per session, from 1. A record of a driver kind has the event's JSON form
without ``kind`` as its ``body`` (``tool.result`` adds ``truncated`` and ``original_bytes``
when clipped); an audit record's body is one of the ``*Body`` models below, as
``as_body()``. ``by`` says who caused the record: the browser (``web``), a deadline
(``timeout``), a close (``closed``), the CLI (``driver``) or the server (``server``).
``text_bytes`` is the UTF-8 size of the body's text, which the log caps count.

Text deltas are never records: they live in a per-session ring and travel as ``DeltaFrame``s
(E8). A stream is a sequence of ``StreamItem``s.
"""

from typing import Final, Literal

from pydantic import Field, JsonValue

from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus, EndReason
from agent_hub.core.agent_sessions.driver import (
    PermissionMode,
    PermissionSuggestion,
    RequestKind,
)
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel

type RecordKind = Literal[
    "init",
    "text",
    "thinking",
    "tool.call",
    "tool.result",
    "todos",
    "permission.request",
    "result",
    "error",
    "exited",
    "user.message",
    "permission.decision",
    "interrupt",
    "settings",
    "close",
    "log.truncated",
    "cloud.start",
    "cloud.followup",
]
# The kinds a driver event becomes (every DriverEvent kind but ``text.delta``).
DRIVER_RECORD_KINDS: Final = frozenset(
    {
        "init",
        "text",
        "thinking",
        "tool.call",
        "tool.result",
        "todos",
        "permission.request",
        "result",
        "error",
        "exited",
    }
)
# The kinds the server writes for what people (or deadlines) did.
AUDIT_RECORD_KINDS: Final = frozenset(
    {
        "user.message",
        "permission.decision",
        "interrupt",
        "settings",
        "close",
        "log.truncated",
        "cloud.start",
        "cloud.followup",
    }
)

type RecordBy = Literal["web", "timeout", "closed", "driver", "server"]


class LogRecord(ViewModel):
    """One persisted record of a session's log."""

    seq: int = Field(ge=1)
    at: ApiTimestamp
    kind: RecordKind
    by: RecordBy | None = None
    body: dict[str, JsonValue]
    text_bytes: int = Field(default=0, ge=0)


class LogRecordPage(ViewModel):
    """``GET /{id}/events``: records after ``after`` in ``seq`` order; ``next_after`` is the
    ``after`` of the next page, None on the last one."""

    items: tuple[LogRecord, ...]
    next_after: int | None = None


class RecordBody(ViewModel):
    """Base of the audit bodies: ``as_body`` drops the fields left at None."""

    def as_body(self) -> dict[str, JsonValue]:
        """The JSON body of the record."""
        body: dict[str, JsonValue] = self.model_dump(mode="json", exclude_none=True)
        return body


class UserMessageBody(RecordBody):
    """``user.message``: what the owner sent (redacted when stored)."""

    text: str


class PermissionRequestBody(RecordBody):
    """``permission.request``: the request and an input summary (at most 4 KiB, redacted when
    stored, E10); ``input`` only for an ``AskUserQuestion`` or a plan approval."""

    request_id: str
    tool: str
    request_kind: RequestKind
    summary: str
    input: dict[str, JsonValue] | None = None
    suggestions: tuple[PermissionSuggestion, ...] = ()


class PermissionDecisionBody(RecordBody):
    """``permission.decision``: how a request was answered; a timeout or a close is ``deny``
    (the record's ``by`` says which)."""

    request_id: str
    decision: Literal["allow", "deny", "always"]
    message: str | None = None
    answers: dict[str, str] | None = None
    suggestion: int | None = None
    mode: PermissionMode | None = None


class SettingsBody(RecordBody):
    """``settings``: the mode or model the owner (or a plan approval) set."""

    mode: PermissionMode | None = None
    model: str | None = None


class LogTruncatedBody(RecordBody):
    """``log.truncated``: the log reached a cap (E12) and the session ends ``log_full``."""

    cap: Literal["records", "bytes"]
    limit: int = Field(ge=0)


class StreamPosition(ViewModel):
    """Where a client resumes (``Last-Event-ID``): after record ``seq`` and, when ``delta``
    is set, after that delta of the open block (E8)."""

    seq: int = Field(ge=0)
    delta: int | None = Field(default=None, ge=0)


class DeltaFrame(ViewModel):
    """A text delta on the wire; ``after_seq`` is the last persisted record (its id is
    ``<after_seq>.<index>``)."""

    frame: Literal["delta"] = "delta"
    after_seq: int = Field(ge=0)
    block: int = Field(ge=0)
    index: int = Field(ge=0)
    text: str


class StatusFrame(ViewModel):
    """The session's status changed."""

    frame: Literal["status"] = "status"
    status: AgentSessionStatus
    end_reason: EndReason | None = None


class ResetFrame(ViewModel):
    """The position cannot be resumed (unknown, older than the log, another session's): the
    client reloads the snapshot and the log."""

    frame: Literal["reset"] = "reset"
    reason: str


type StreamItem = LogRecord | DeltaFrame | StatusFrame | ResetFrame
