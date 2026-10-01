"""Root of the agent-hub exception hierarchy; each package defines its own subclasses."""

from agent_hub.core.hub_config.problems import one_line


class AgentHubError(Exception):
    """Base class for every error agent-hub raises on purpose."""


class EventConflictError(AgentHubError):
    """An event has the key ``(source, source_id)`` of another event but different content.

    ``position`` is the index, in the appended batch, of the event that conflicts.
    """

    def __init__(self, *, source: str, source_id: str, position: int) -> None:
        self.source = source
        self.source_id = source_id
        self.position = position
        super().__init__(
            f"event ({source}, {source_id}) at position {position} differs from an event "
            "with the same key"
        )


class TrackerError(AgentHubError):
    """A tracker operation failed; the message names the operation, issue, cause and fix.

    The message is one line, ``"<operation> <issue_id>: <cause>; <fix>"`` (no issue id for an
    operation without one). Control characters are escaped, because the cause may quote
    untrusted text such as an issue title or a tracker reply.
    """

    def __init__(
        self, *, operation: str, issue_id: str | None = None, cause: str, fix: str
    ) -> None:
        self.operation = operation
        self.issue_id = issue_id
        subject = operation if issue_id is None else f"{operation} {issue_id}"
        super().__init__(one_line(f"{subject}: {cause}; {fix}"))
