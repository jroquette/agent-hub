"""The errors of agent sessions; ``api/rfc9457.py`` maps each to one problem (RT).

Messages name ids, limits and causes only: never conversation text, tool input or a path the
browser sent (privacy NFR).
"""

from agent_hub.core.errors import AgentHubError
from agent_hub.core.readmodels.read_ports import EntityNotFoundError


class AgentSessionNotFoundError(EntityNotFoundError):
    """No agent session has this id (404)."""

    def __init__(self, agent_session_id: str) -> None:
        super().__init__(entity="agent session", entity_id=agent_session_id)


class SessionTerminalError(AgentHubError):
    """The session has ended or failed; only Resume goes on (409)."""

    def __init__(self, agent_session_id: str, *, status: str) -> None:
        self.agent_session_id = agent_session_id
        self.status = status
        super().__init__(f"agent session {agent_session_id} is {status}; resume it to go on")


class SessionBusyError(AgentHubError):
    """An interrupt is pending: the next message waits for the turn's result (409)."""

    def __init__(self, agent_session_id: str) -> None:
        self.agent_session_id = agent_session_id
        super().__init__(f"agent session {agent_session_id} is ending its turn; try again")


class SessionLiveError(SessionBusyError):
    """The session is live: close it before deleting it (409, as a busy session)."""

    def __init__(self, agent_session_id: str) -> None:
        self.agent_session_id = agent_session_id
        AgentHubError.__init__(
            self, f"agent session {agent_session_id} is live; close it before deleting it"
        )


class LiveLimitError(AgentHubError):
    """As many sessions as allowed are live; close one first (429)."""

    def __init__(self, *, limit: int) -> None:
        self.limit = limit
        super().__init__(f"at most {limit} live agent sessions; close one to start another")


class LogFullError(AgentHubError):
    """The session's log reached its cap (E12); only Resume goes on (409)."""

    def __init__(self, agent_session_id: str) -> None:
        self.agent_session_id = agent_session_id
        super().__init__(f"agent session {agent_session_id} log is full; Resume to go on")


class PermissionAnsweredError(AgentHubError):
    """The permission request was already answered; the first answer won (409)."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(f"permission request {request_id} was already answered")


class UnknownPermissionError(AgentHubError):
    """No pending permission request has this id (404)."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(f"no pending permission request {request_id}")


class InvalidDecisionError(AgentHubError):
    """The answer does not fit the request (E7: a suggestion not ``localSettings``, answers
    to a tool request, a mode outside a plan approval) (422)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"invalid permission answer: {reason}")


class InvalidWorkdirError(AgentHubError):
    """The workdir id is not one ``GET /workdirs`` lists for the project (422)."""

    def __init__(self, workdir_id: str) -> None:
        self.workdir_id = workdir_id
        super().__init__(f"no workdir {workdir_id!r} in this project")


class UnknownResumeError(AgentHubError):
    """The session to resume is not one ``GET /resumable`` lists for the workdir (422)."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"no resumable session {session_id!r} in this workdir")


class MessageTooLargeError(AgentHubError):
    """A message or prompt is over the UTF-8 byte limit (413)."""

    def __init__(self, *, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(f"message of {size} bytes is over the {limit} byte limit")


class SessionsUnavailableError(AgentHubError):
    """Sessions cannot start on this machine: no ``claude``, or the extra not installed (503)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"agent sessions unavailable: {reason}")


class SessionsOffError(AgentHubError):
    """Session control is off in the container (L2) (404 ``agent-sessions-off``)."""

    def __init__(self) -> None:
        super().__init__("agent sessions are off in the container")


class CloudUnavailableError(AgentHubError):
    """The installed ``claude`` cannot start or follow up cloud sessions (501, guidance)."""

    def __init__(self, guidance: str) -> None:
        self.guidance = guidance
        super().__init__(f"cloud sessions unavailable: {guidance}")


class CloudFailedError(AgentHubError):
    """A cloud command failed or answered what cannot be read (502); ``step`` names it."""

    def __init__(self, step: str) -> None:
        self.step = step
        super().__init__(f"cloud command failed at {step}")


class CloudTimeoutError(AgentHubError):
    """A cloud command passed its deadline and was stopped (504)."""

    def __init__(self, *, seconds: int) -> None:
        self.seconds = seconds
        super().__init__(f"cloud command passed its {seconds} s deadline")


class StoreSequenceError(AgentHubError):
    """An append would leave a gap or repeat a ``seq``: the log stays gap-free."""

    def __init__(self, agent_session_id: str, *, expected: int, got: int) -> None:
        self.agent_session_id = agent_session_id
        self.expected = expected
        self.got = got
        super().__init__(f"agent session {agent_session_id}: expected seq {expected}, got {got}")


class InvalidScreenshotError(AgentHubError):
    """The screenshot is not valid base64 or not a PNG (422); ``reason`` is fixed text, never
    the data."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"invalid screenshot: {reason}")


class ScreenshotTooLargeError(AgentHubError):
    """The decoded screenshot is over the byte limit (413)."""

    def __init__(self, *, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(f"screenshot of {size} bytes is over the {limit} byte limit")
