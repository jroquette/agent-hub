"""``InMemoryAgentSessionStore``: the ``AgentSessionStore`` port over dictionaries."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Unpack

from agent_hub.core.agent_sessions.agent_session import (
    TERMINAL_STATUSES,
    AgentSession,
    AgentSessionKind,
    AgentSessionStatus,
    EndReason,
)
from agent_hub.core.agent_sessions.errors import AgentSessionNotFoundError, StoreSequenceError
from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.agent_sessions.store import AgentSessionFields


class InMemoryAgentSessionStore:
    """Sessions and their records in memory; behaves as ``AgentSessionStoreContract`` says."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._records: dict[str, list[LogRecord]] = {}

    def create(self, session: AgentSession) -> None:
        """Store a new session; an id twice or a non-zero ``last_seq`` is refused."""
        if session.id in self._sessions:
            msg = f"agent session {session.id} exists"
            raise ValueError(msg)
        if session.last_seq != 0:
            msg = "a new agent session starts at last_seq 0"
            raise ValueError(msg)
        self._sessions[session.id] = session.model_copy(update={"open_permission": None})
        self._records[session.id] = []

    def append(self, agent_session_id: str, records: Sequence[LogRecord]) -> None:
        """Add records gap-free, all or none."""
        session = self.get(agent_session_id)
        expected = session.last_seq + 1
        for record in records:
            if record.seq != expected:
                raise StoreSequenceError(agent_session_id, expected=expected, got=record.seq)
            expected += 1
        self._records[agent_session_id].extend(records)
        self._sessions[agent_session_id] = session.model_copy(update={"last_seq": expected - 1})

    def update(self, agent_session_id: str, **fields: Unpack[AgentSessionFields]) -> AgentSession:
        """Change some fields, validated as the model says."""
        session = self.get(agent_session_id)
        updated = AgentSession.model_validate(session.model_dump() | dict(fields))
        self._sessions[agent_session_id] = updated
        return updated

    def get(self, agent_session_id: str) -> AgentSession:
        """One session."""
        if agent_session_id not in self._sessions:
            raise AgentSessionNotFoundError(agent_session_id)
        return self._sessions[agent_session_id]

    def list(
        self,
        *,
        project: str | None = None,
        status: AgentSessionStatus | None = None,
        kind: AgentSessionKind | None = None,
        limit: int = 200,
    ) -> tuple[AgentSession, ...]:
        """Matching sessions, newest first."""
        matching = [
            session
            for session in self._sessions.values()
            if (project is None or session.project == project)
            and (status is None or session.status == status)
            and (kind is None or session.kind == kind)
        ]
        matching.sort(key=lambda session: (session.created_at, session.id), reverse=True)
        return tuple(matching[:limit])

    def records(
        self,
        agent_session_id: str,
        *,
        after: int = 0,
        limit: int = 200,
        kinds: Collection[RecordKind] | None = None,
    ) -> tuple[LogRecord, ...]:
        """Records after ``after``, in ``seq`` order (of ``kinds`` only, when given)."""
        self.get(agent_session_id)
        later = [
            record
            for record in self._records[agent_session_id]
            if record.seq > after and (kinds is None or record.kind in kinds)
        ]
        return tuple(later[:limit])

    def link_of(self, project: str, claude_session_id: str) -> str | None:
        """The newest session of ``project`` driving that Claude session."""
        for session in self.list(project=project):
            if session.claude_session_id == claude_session_id:
                return session.id
        return None

    def end_unfinished(self, at: datetime, reason: EndReason) -> int:
        """End every non-terminal session."""
        unfinished = [
            session.id
            for session in self._sessions.values()
            if session.status not in TERMINAL_STATUSES
        ]
        for agent_session_id in unfinished:
            self.update(
                agent_session_id,
                status=AgentSessionStatus.ENDED,
                end_reason=reason,
                ended_at=at,
                updated_at=at,
            )
        return len(unfinished)

    def purge_ended_before(self, cutoff: datetime) -> int:
        """Remove terminal sessions that ended before ``cutoff``."""
        old = [
            session.id
            for session in self._sessions.values()
            if session.status in TERMINAL_STATUSES
            and session.ended_at is not None
            and session.ended_at < cutoff
        ]
        for agent_session_id in old:
            self.delete(agent_session_id)
        return len(old)

    def delete(self, agent_session_id: str) -> None:
        """Remove a session and its records."""
        self.get(agent_session_id)
        del self._sessions[agent_session_id]
        del self._records[agent_session_id]
