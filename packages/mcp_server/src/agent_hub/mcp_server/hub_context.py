"""What ``hub mcp``'s tools are given about the hub, and how a tool refuses a call."""

from agent_hub.core.errors import AgentHubError


class ToolRefusal(AgentHubError):  # noqa: N818 - a tool's answer, read as "the tool refused"
    """A tool call refused before or while it ran; ``line`` is the one-line tool error the
    caller sees (``<tool>: <reason>``), never holding the caller's text or a match."""

    def __init__(self, line: str) -> None:
        self.line = line
        super().__init__(line)
