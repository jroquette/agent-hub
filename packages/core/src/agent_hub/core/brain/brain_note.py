"""The brain browser's read models: a hub's tree of notes and one note (D3, S8).

Notes are read from the registered hub's ``brain/`` on request and never stored; paths here are
relative to ``brain/`` with ``/`` separators.
"""

from pydantic import Field

from agent_hub.core.errors import AgentHubError
from agent_hub.core.readmodels.view_types import ViewModel

type FrontmatterValue = str | list[str]


class BrainEntry(ViewModel):
    """One ``.md`` note of the tree and its size in bytes."""

    path: str
    size: int = Field(ge=0)


class BrainTree(ViewModel):
    """The ``.md`` notes of a hub's brain, sorted by path (``auto/`` and hidden names excluded).

    ``truncated`` says the listing stopped at a cap; ``skipped`` counts what was left out
    (unreadable folders, entries past a cap).
    """

    project: str
    entries: tuple[BrainEntry, ...]
    truncated: bool = False
    skipped: int = Field(default=0, ge=0)


class BrainNote(ViewModel):
    """One note: its frontmatter fields, its markdown body (without the frontmatter) and size.

    ``frontmatter_problem`` says why the frontmatter could not be read (then ``frontmatter`` is
    empty and ``markdown`` is the whole text).
    """

    project: str
    path: str
    frontmatter: dict[str, FrontmatterValue]
    frontmatter_problem: str | None = None
    markdown: str
    size: int = Field(ge=0)


class BrainNoteNotFoundError(AgentHubError):
    """No readable note at ``path``: missing, a link, not a regular file or excluded (``auto/``).

    The cases share one error so a response never reveals which of them it was.
    """

    def __init__(self, *, project: str, path: str) -> None:
        self.project = project
        self.path = path
        super().__init__(f"no brain note {path!r} in project {project!r}")


class BrainNoteTooLargeError(AgentHubError):
    """The note at ``path`` is larger than ``limit`` bytes."""

    def __init__(self, *, project: str, path: str, size: int, limit: int) -> None:
        self.project = project
        self.path = path
        self.size = size
        self.limit = limit
        super().__init__(f"brain note {path!r} is {size} bytes, over the {limit}-byte limit")
