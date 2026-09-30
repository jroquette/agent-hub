"""``RenderedLink``: one symlink of a hub, rendered in memory (docs/design/hub-generator.md)."""

import posixpath
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RelativePosixPath, check_module


def _form_problem(target: str) -> str | None:
    # Checked in this order so the message names the first thing wrong with the target.
    if not target:
        return "must not be empty"
    if "\x00" in target:
        return "must not contain NUL"
    if "\\" in target:
        return "must use / as the separator, not \\"
    if target.startswith("/"):
        return "must be relative, not absolute"
    # Canonical form: ``..`` only as leading segments, so no segment can pass through another link.
    if posixpath.normpath(target) != target or target.endswith("/"):
        return "must be a normalized POSIX path"
    return None


def link_target_problem(path: str | None, target: str) -> str | None:
    """What is wrong with ``target`` for a link at ``path``, or ``None`` when it stays in the hub.

    ``hub.lock`` applies the same rule to the link targets it reads back.
    """
    problem = _form_problem(target)
    if problem is not None or path is None:
        # With an invalid path (already reported) there is no folder to resolve from.
        return problem
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    if resolved == ".." or resolved.startswith("../"):
        return f"resolves outside the hub from {path!r}"
    if resolved in {".", path}:
        return f"must not point at the hub root or at itself from {path!r}"
    return None


class RenderedLink(BaseModel):
    """A symlink of a hub: its relative POSIX path, its relative target and its classification.

    ``target`` is relative to the link's folder and resolves inside the hub. ``module`` follows
    ``RenderedFile``'s rule. These are checks only: the model holds no behavior.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: RelativePosixPath
    target: str
    kind: Kind
    ownership: Ownership
    module: str | None

    @field_validator("target")
    @classmethod
    def _target_inside_hub(cls, target: str, info: ValidationInfo) -> str:
        problem = link_target_problem(info.data.get("path"), target)
        if problem is not None:
            msg = f"target {target!r} {problem}"
            raise ValueError(msg)
        return target

    @model_validator(mode="after")
    def _module_matches_kind(self) -> Self:
        check_module(self.kind, self.module)
        return self
