"""Cloud sessions (D8): ``CloudSessionCommands`` is what the cloud routes call.

``CloudSessions`` implements them over the ``CloudLauncher`` port (the ``claude`` CLI, in
``agent_hub.claude_sessions``) and the agent-session store. What the spike found (L9) shapes it:

- **Start is link-out guidance.** ``claude --cloud "<task>"`` needs an interactive terminal, so
  ``start`` never runs it: it raises ``CloudUnavailableError`` with the commands to run in a
  terminal (or, when the CLI has no ``--cloud``, how to get one). The task is never echoed.
- **A follow-up is behind ``capabilities.cloud_followup``** (off until the owner has seen what
  ``claude -p --cloud <id> --output-format json`` answers). It needs a persisted cloud row of
  that id; it is logged as a ``cloud.followup`` record (the cloud id only, never the text).
- A URL is kept only when it starts with ``https://claude.ai/code/``.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Final, Protocol

from agent_hub.core.agent_sessions.agent_session import (
    CLOUD_ID_PATTERN,
    AgentSession,
    CloudMessage,
    CloudSession,
    CloudSessionList,
    StartCloud,
)
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.agent_sessions.errors import AgentSessionNotFoundError, CloudUnavailableError
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.records import LogRecord
from agent_hub.core.agent_sessions.store import AgentSessionStore
from agent_hub.core.readmodels.view_types import ViewModel

CLAUDE_CODE_URL_PREFIX: Final = "https://claude.ai/code/"
MAX_CLOUD_LISTED: Final = 50
START_GUIDANCE: Final = (
    'Starting a cloud session needs a terminal: run claude --cloud "<task>" in this workdir, '
    f"then open it at {CLAUDE_CODE_URL_PREFIX} or bring it here with claude --teleport <id>."
)
NO_CLOUD_GUIDANCE: Final = (
    "The installed claude has no --cloud: update Claude Code, or start the session at "
    f"{CLAUDE_CODE_URL_PREFIX}."
)
FOLLOWUP_GUIDANCE: Final = (
    f"Follow-ups from here are off: open the session at {CLAUDE_CODE_URL_PREFIX} or bring it "
    "here with claude --teleport <id>."
)
_CLOUD_ID = re.compile(CLOUD_ID_PATTERN)


class CloudSessionCommands(Protocol):
    """Start a cloud session, follow one up, list the persisted starts."""

    async def list_cloud(self, project: str | None) -> CloudSessionList:
        """Persisted cloud starts, newest first, at most 50."""
        ...

    async def start(self, request: StartCloud) -> CloudSession:
        """Run ``claude --cloud <task>`` and record what it answered."""
        ...

    async def follow_up(self, cloud_id: str, message: CloudMessage) -> CloudSession:
        """Run ``claude -p <text> --cloud <id> --output-format json`` once."""
        ...


class CloudReply(ViewModel):
    """What a follow-up answered: the session id and, when given, its URL (not yet checked)."""

    cloud_id: str
    url: str | None = None


class CloudLauncher(Protocol):
    """Runs the ``claude`` cloud commands."""

    async def follow_up(self, cloud_id: str, text: str, *, timeout_seconds: int) -> CloudReply:
        """Run ``claude -p --cloud <id> --output-format json <text>`` once.

        ``CloudFailedError`` when it fails or answers what cannot be read, ``CloudTimeoutError``
        past the deadline.
        """
        ...


def claude_code_url(url: str | None) -> str | None:
    """``url`` when it is a claude.ai/code link, else None (never shown as a link)."""
    if url is None or not url.startswith(CLAUDE_CODE_URL_PREFIX):
        return None
    return url


def teleport_command(cloud_id: str) -> str:
    """The command that brings the cloud session to a local terminal."""
    return f"claude --teleport {cloud_id}"


def _shown(row: AgentSession) -> CloudSession:
    cloud_id = row.cloud_id or ""
    return CloudSession(
        id=row.id,
        project=row.project,
        workdir_id=row.workdir_id,
        cloud_id=cloud_id,
        url=claude_code_url(row.url),
        teleport_command=teleport_command(cloud_id),
        title=row.title,
        created_at=row.created_at,
        followups=max(row.last_seq - 1, 0),
    )


class CloudSessions:
    """``CloudSessionCommands`` over the launcher and the store; see the module docstring."""

    def __init__(
        self,
        *,
        launcher: CloudLauncher,
        store: AgentSessionStore,
        capabilities: Callable[[], Awaitable[DriverCapabilities]],
        clock: Callable[[], datetime],
        limits: SessionLimits | None = None,
    ) -> None:
        self._launcher = launcher
        self._store = store
        self._capabilities = capabilities
        self._clock = clock
        self._limits = limits or SessionLimits()

    async def list_cloud(self, project: str | None) -> CloudSessionList:
        """Persisted cloud starts, newest first, at most 50."""
        rows = await asyncio.to_thread(
            self._store.list, project=project, kind="cloud", limit=MAX_CLOUD_LISTED
        )
        return CloudSessionList(items=tuple(_shown(row) for row in rows))

    async def start(self, request: StartCloud) -> CloudSession:
        """Always guidance (the CLI's start needs a terminal); see the module docstring."""
        del request
        capabilities = await self._capabilities()
        raise CloudUnavailableError(START_GUIDANCE if capabilities.cloud else NO_CLOUD_GUIDANCE)

    async def follow_up(self, cloud_id: str, message: CloudMessage) -> CloudSession:
        """Send one follow-up to a persisted cloud session and log it."""
        capabilities = await self._capabilities()
        if not capabilities.cloud_followup:
            raise CloudUnavailableError(FOLLOWUP_GUIDANCE)
        row = await self._row(cloud_id)
        reply = await self._launcher.follow_up(
            cloud_id, message.text, timeout_seconds=self._limits.cloud_timeout_seconds
        )
        now = self._clock()
        record = LogRecord(
            seq=row.last_seq + 1,
            at=now,
            kind="cloud.followup",
            by="web",
            body={"cloud_id": cloud_id},
        )
        await asyncio.to_thread(self._store.append, row.id, [record])
        url = claude_code_url(reply.url) or claude_code_url(row.url)
        updated = await asyncio.to_thread(self._store.update, row.id, url=url, updated_at=now)
        return _shown(updated)

    async def _row(self, cloud_id: str) -> AgentSession:
        if _CLOUD_ID.fullmatch(cloud_id) is not None and not cloud_id.startswith("-"):
            rows = await asyncio.to_thread(self._store.list, kind="cloud")
            for row in rows:
                if row.cloud_id == cloud_id:
                    return row
        raise AgentSessionNotFoundError(cloud_id)
