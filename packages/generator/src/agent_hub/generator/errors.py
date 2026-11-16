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


class FileWriteError(GeneratorError):
    """A path of the hub could not be written or removed: ``cause`` says why (``strerror``)."""

    def __init__(self, *, path: str, cause: str) -> None:
        self.path = path
        self.cause = cause
        super().__init__(f"{path}: {cause}")


class SymlinkedAncestorError(GeneratorError):
    """A folder above ``path`` is a symlink at write time: nothing is written through it."""

    def __init__(self, *, path: str, ancestor: str) -> None:
        self.path = path
        self.ancestor = ancestor
        super().__init__(f"{path}: symlinked ancestor {ancestor}")


class LinkOutsideHubError(GeneratorError):
    """The link to write at ``path`` would resolve outside the hub root."""

    def __init__(self, *, path: str) -> None:
        self.path = path
        super().__init__(f"{path}: resolves outside the hub")
