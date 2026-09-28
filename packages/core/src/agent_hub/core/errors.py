"""Root of the agent-hub exception hierarchy; each package defines its own subclasses."""


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
