"""Errors raised by the generator."""

from agent_hub.core.errors import AgentHubError


class GeneratorError(AgentHubError):
    """Base class for generator errors."""


class TemplateError(GeneratorError):
    """A template cannot be rendered: an unknown or malformed placeholder."""
