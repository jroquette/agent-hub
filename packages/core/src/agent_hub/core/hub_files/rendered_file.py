"""``RenderedFile``: one file of a hub, rendered in memory (docs/design/hub-generator.md)."""

import posixpath
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, model_validator

from agent_hub.core.hub_config.model import MODULE_IDS


class Kind(StrEnum):
    """The closed list of file kinds: where a file's content comes from."""

    GENERIC = "generic"
    MODULE = "module"
    PROJECT_OWNED = "project-owned"


class Ownership(StrEnum):
    """The closed list of ownerships: who changes a file after it is written."""

    MANAGED = "managed"
    SEEDED = "seeded"


def _path_problem(path: str) -> str | None:
    # Checked in this order so the message names the first thing wrong with the path.
    if not path:
        return "must not be empty"
    if "\\" in path:
        return "must use / as the separator, not \\"
    if path.startswith("/"):
        return "must be relative, not absolute"
    if path.endswith("/"):
        return "must not end with /"
    if any(segment in {"", ".", ".."} for segment in path.split("/")):
        return "must have no empty, . or .. segment"
    if posixpath.normpath(path) != path:
        return "must be a normalized POSIX path"
    return None


def _relative_posix_path(path: str) -> str:
    problem = _path_problem(path)
    if problem is not None:
        msg = f"path {path!r} {problem}"
        raise ValueError(msg)
    return path


# Relative, normalized, POSIX: where the file lands under the hub root, on any system. A plain
# alias, not a ``type`` statement, so the field's annotation stays ``str``.
RelativePosixPath = Annotated[str, AfterValidator(_relative_posix_path)]


class RenderedFile(BaseModel):
    """A file of a hub: its relative POSIX path, its bytes and its classification.

    ``module`` is set exactly when ``kind`` is ``module``, and is then one of ``MODULE_IDS``.
    These are checks only: the model holds no behavior.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: RelativePosixPath
    content: bytes
    executable: bool
    kind: Kind
    ownership: Ownership
    module: str | None

    @model_validator(mode="after")
    def _module_matches_kind(self) -> Self:
        if self.kind is Kind.MODULE and self.module is None:
            msg = "module must be set when kind is module"
            raise ValueError(msg)
        if self.kind is not Kind.MODULE and self.module is not None:
            msg = f"module must be unset when kind is {self.kind.value}, got {self.module!r}"
            raise ValueError(msg)
        if self.module is not None and self.module not in MODULE_IDS:
            msg = f"module {self.module!r} is not one of {', '.join(MODULE_IDS)}"
            raise ValueError(msg)
        return self
