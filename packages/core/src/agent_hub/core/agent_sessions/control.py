"""``AgentSessionCommands``: what the agent-session routes call, one method per route.

``AgentSessionControl`` (UC) implements it: it owns the live sessions in ``hub web``'s event
loop, pumps driver events into the persisted, redacted log and wakes the streams. The routes
and their tests depend only on this Protocol (K.6), so they are built before the class.
Errors are the ``errors`` module's; the API maps each to a problem.
"""

from collections.abc import AsyncIterator
from typing import Protocol

from agent_hub.core.agent_sessions.agent_session import (
    AgentSession,
    AgentSessionList,
    AgentSessionStatus,
    CreateAgentSession,
    MessageAccepted,
    PermissionDecision,
    ResumableList,
    SendMessage,
    SessionSettings,
    WorkdirList,
)
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.agent_sessions.records import LogRecordPage, StreamItem, StreamPosition


class AgentSessionCommands(Protocol):
    """Every agent-session use case the routes reach (S3, P5)."""

    async def workdirs(self, project: str) -> WorkdirList:
        """The folders a session of ``project`` may start in (D6)."""
        ...

    async def capabilities(self) -> DriverCapabilities:
        """Whether sessions can start here, and the cloud commands (S8)."""
        ...

    async def resumable(self, project: str, workdir_id: str) -> ResumableList:
        """Past Claude sessions of one workdir (D7)."""
        ...

    async def list_sessions(
        self, *, project: str | None, status: AgentSessionStatus | None
    ) -> AgentSessionList:
        """Local agent sessions, newest first."""
        ...

    async def create(self, request: CreateAgentSession) -> AgentSession:
        """Start a session (and send its first prompt): ``running`` with a prompt, else
        ``idle`` (E13)."""
        ...

    async def snapshot(self, agent_session_id: str) -> AgentSession:
        """One session, with its open permission request while live (E10)."""
        ...

    async def delete(self, agent_session_id: str) -> None:
        """Remove an ended session and its log (L4); a live one raises."""
        ...

    async def events(self, agent_session_id: str, *, after: int, limit: int) -> LogRecordPage:
        """A page of the persisted log after ``after``."""
        ...

    async def subscribe(
        self, agent_session_id: str, after: StreamPosition | None
    ) -> AsyncIterator[StreamItem]:
        """The stream from ``after`` (E8): stored records, ring deltas, then live frames.

        Awaiting it checks the session (and the subscriber cap) before any byte is sent.
        """
        ...

    async def send(self, agent_session_id: str, message: SendMessage) -> MessageAccepted:
        """Log and pass on a user message."""
        ...

    async def interrupt(self, agent_session_id: str) -> AgentSession:
        """Interrupt the running turn; its result follows on the stream."""
        ...

    async def answer(
        self, agent_session_id: str, request_id: str, decision: PermissionDecision
    ) -> AgentSession:
        """Answer an open permission request (once)."""
        ...

    async def change_settings(
        self, agent_session_id: str, settings: SessionSettings
    ) -> AgentSession:
        """Change the mode or model."""
        ...

    async def close(self, agent_session_id: str) -> AgentSession:
        """End the session (idempotent)."""
        ...
