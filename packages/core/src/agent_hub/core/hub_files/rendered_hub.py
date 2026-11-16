"""``RenderedHub``: a hub's files and links, rendered in memory (docs/design/hub-generator.md)."""

from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from agent_hub.core.hub_files.rendered_file import RenderedFile
from agent_hub.core.hub_files.rendered_link import RenderedLink


def _order_problem(name: str, paths: Sequence[str]) -> str | None:
    if list(paths) != sorted(paths):
        return f"{name} must be sorted by path"
    for previous, current in zip(paths, paths[1:], strict=False):
        if previous == current:
            return f"path {current!r} appears more than once in {name}"
    return None


class RenderedHub(BaseModel):
    """A hub's files and links: each tuple sorted by path, and no path used twice.

    These are checks only: the model holds no behavior.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    files: tuple[RenderedFile, ...]
    links: tuple[RenderedLink, ...]

    @model_validator(mode="after")
    def _paths_sorted_and_unique(self) -> Self:
        file_paths = [rendered.path for rendered in self.files]
        link_paths = [link.path for link in self.links]
        for name, paths in (("files", file_paths), ("links", link_paths)):
            problem = _order_problem(name, paths)
            if problem is not None:
                raise ValueError(problem)
        shared = sorted(set(file_paths) & set(link_paths))
        if shared:
            msg = f"path {shared[0]!r} is both a file and a link"
            raise ValueError(msg)
        # Nothing may be written through a link: no path lies under a link's path.
        for link_path in link_paths:
            for path in (*file_paths, *link_paths):
                if path.startswith(link_path + "/"):
                    msg = f"path {path!r} is under link {link_path!r}"
                    raise ValueError(msg)
        return self
