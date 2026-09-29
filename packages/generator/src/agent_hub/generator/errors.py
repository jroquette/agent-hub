"""Errors raised by the generator."""

from agent_hub.core.errors import AgentHubError


class GeneratorError(AgentHubError):
    """Base class for generator errors."""


class TemplateError(GeneratorError):
    """A template cannot be rendered: an unknown or malformed placeholder.

    ``source`` names the template, ``placeholder`` the offending placeholder, ``reason`` what is
    wrong with it.
    """

    def __init__(self, *, source: str, placeholder: str, reason: str) -> None:
        self.source = source
        self.placeholder = placeholder
        super().__init__(f"{source}: {reason}: {placeholder}")
