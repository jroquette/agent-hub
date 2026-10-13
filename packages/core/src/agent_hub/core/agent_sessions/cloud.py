"""Cloud sessions (D8): ``CloudSessionCommands`` is what the cloud routes call.

The ``CloudLauncher`` port and the ``CloudSessions`` use case that implements these commands
come with the cloud stream (CL), after the spike says what ``claude --cloud`` answers (L9).
"""

from typing import Protocol

from agent_hub.core.agent_sessions.agent_session import (
    CloudMessage,
    CloudSession,
    CloudSessionList,
    StartCloud,
)


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
