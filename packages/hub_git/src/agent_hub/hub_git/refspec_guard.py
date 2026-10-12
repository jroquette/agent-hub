"""The push guard of the learning actions (L8, ADR 0024): the only way the adapter builds a push.

``push_argv`` refuses, before git runs, the default branch, a forced (``+``) or mapped (``:``)
refspec, any force flag, an invalid ref name and any branch outside ``<prefix>learning-``. What
it returns pushes (or deletes) exactly one branch of that name on ``origin``, never forced, so
git itself also refuses to overwrite a branch that already exists there.
"""

import re
from typing import Final

from agent_hub.core.learnings.brain_change_requests import RefspecRefusedError

LEARNING_PART: Final = "learning-"
HEADS: Final = "refs/heads/"
_REMOTE: Final = "origin"
# A conservative ref name: letters, digits and ``._/-`` only (no space, control, ``~^:?*[\@{``).
_NAME: Final = re.compile(r"[A-Za-z0-9._/-]+")
_BAD_PARTS: Final = ("..", "//", "/.", ".lock/")


def _refuse_forms(branch: str) -> None:
    if branch.startswith("-"):
        raise RefspecRefusedError(f"Push refused: {branch!r} is an option, not a branch")
    if "+" in branch:
        raise RefspecRefusedError("Push refused: a forced refspec")
    if ":" in branch:
        raise RefspecRefusedError("Push refused: a refspec that maps or deletes a ref")


def _refuse_name(branch: str) -> None:
    valid = (
        _NAME.fullmatch(branch) is not None
        and not any(part in f"{branch}/" for part in _BAD_PARTS)
        and not branch.startswith(("/", "."))
        and not branch.endswith(("/", "."))
    )
    if not valid:
        raise RefspecRefusedError(f"Push refused: {branch!r} is not a valid branch name")


def _refuse_default(branch: str, default_branch: str) -> None:
    named = branch.removeprefix(HEADS)
    if named == default_branch or branch.startswith("refs/"):
        raise RefspecRefusedError("Push refused: the default branch is never pushed")


def _refuse_outside_learning(branch: str, prefix: str) -> None:
    start = f"{prefix}{LEARNING_PART}"
    if not branch.startswith(start) or len(branch) == len(start):
        raise RefspecRefusedError(f"Push refused: {branch!r} is not a {start}<name> branch")


def push_argv(branch: str, *, default_branch: str, prefix: str, delete: bool = False) -> list[str]:
    """The git arguments that push (or, with ``delete``, delete) ``branch`` on ``origin``.

    Raises ``RefspecRefusedError`` naming the reason for the default branch (or a ``refs/``
    name), a ``+`` or ``:`` refspec, an option such as ``--force`` or ``-f``, an invalid ref name,
    and a branch outside ``<prefix>learning-``.
    """
    _refuse_forms(branch)
    _refuse_default(branch, default_branch)
    _refuse_name(branch)
    _refuse_outside_learning(branch, prefix)
    ref = f"{HEADS}{branch}"
    if delete:
        return ["push", "--no-verify", _REMOTE, "--delete", ref]
    return ["push", "--no-verify", _REMOTE, f"{ref}:{ref}"]
