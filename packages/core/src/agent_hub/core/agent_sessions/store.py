"""The ``AgentSessionStore`` port: agent sessions and their logs, persisted (P3, P10).

Synchronous (SQLAlchemy Core over SQLite in production); ``AgentSessionControl`` calls it off
the event loop. ``AgentSessionStoreContract`` checks every implementation:

- ``append`` keeps ``seq`` gap-free: the first record of a batch is ``last_seq + 1`` and each
  next one adds 1, else ``StoreSequenceError`` and nothing is written. It moves ``last_seq``.
- ``records`` and ``list`` keep order (``seq``; newest ``created_at`` first).
- ``open_permission`` is never stored: ``get`` and ``list`` answer it as None.
- ``end_unfinished`` ends every non-terminal session (a crash left it so); ``purge_ended_before``
  removes terminal sessions that ended before the cutoff, with their records, and never a live
  one; ``delete`` removes one session and its records.
- An unknown id raises ``AgentSessionNotFoundError``.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, TypedDict, Unpack

from agent_hub.core.agent_sessions.agent_session import (
    AgentSession,
    AgentSessionKind,
    AgentSessionStatus,
    EndReason,
)
from agent_hub.core.agent_sessions.driver import PermissionMode
from agent_hub.core.agent_sessions.records import LogRecord
from agent_hub.core.readmodels.view_types import Money
from agent_hub.core.sessions.session import TokenUsage


class AgentSessionFields(TypedDict, total=False):
    """The fields ``update`` may change; the others are set once by ``create``."""

    claude_session_id: str | None
    cloud_id: str | None
    url: str | None
    status: AgentSessionStatus
    mode: PermissionMode
    model: str | None
    title: str | None
    updated_at: datetime
    ended_at: datetime | None
    end_reason: EndReason | None
    cost_usd: Money | None
    usage: TokenUsage | None


class AgentSessionStore(Protocol):
    """Where agent sessions and their logs are kept."""

    def create(self, session: AgentSession) -> None:
        """Store a new session (its ``last_seq`` must be 0)."""
        ...

    def append(self, agent_session_id: str, records: Sequence[LogRecord]) -> None:
        """Add records to the session's log, gap-free, in one transaction."""
        ...

    def update(self, agent_session_id: str, **fields: Unpack[AgentSessionFields]) -> AgentSession:
        """Change some fields; answers the session as stored now."""
        ...

    def get(self, agent_session_id: str) -> AgentSession:
        """One session."""
        ...

    def list(
        self,
        *,
        project: str | None = None,
        status: AgentSessionStatus | None = None,
        kind: AgentSessionKind | None = None,
        limit: int = 200,
    ) -> tuple[AgentSession, ...]:
        """Sessions matching every filter given, newest first, at most ``limit``."""
        ...

    def records(
        self, agent_session_id: str, *, after: int = 0, limit: int = 200
    ) -> tuple[LogRecord, ...]:
        """The session's records with ``seq`` above ``after``, in order, at most ``limit``."""
        ...

    def link_of(self, project: str, claude_session_id: str) -> str | None:
        """The id of the newest agent session of ``project`` driving that Claude session."""
        ...

    def end_unfinished(self, at: datetime, reason: EndReason) -> int:
        """End every session not yet ``ended`` or ``failed``; answers how many."""
        ...

    def purge_ended_before(self, cutoff: datetime) -> int:
        """Remove terminal sessions that ended before ``cutoff``, with their records."""
        ...

    def delete(self, agent_session_id: str) -> None:
        """Remove one session and its records."""
        ...
