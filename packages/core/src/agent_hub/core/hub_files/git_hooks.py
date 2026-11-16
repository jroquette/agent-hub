"""Where a hub's git hooks live, and whether ``core.hooksPath`` may point git at them (ADR 0061).

``hub sync`` renders ``.githooks/pre-commit`` and ``.githooks/commit-msg``; git runs them once the
hub's ``core.hooksPath`` is ``.githooks`` (a relative path: each worktree runs its own copy).
``hub sync`` and ``hub setup`` set it when it is unset, or when it names ``.git/hooks`` (git's
default, where ``pre-commit install`` used to put the hub's hooks); any other value is the
developer's own hook manager, left as it is with a note.
"""

from enum import StrEnum
from typing import Final

GIT_HOOKS_FOLDER: Final = ".githooks"
HOOKS_PATH_KEY: Final = "core.hooksPath"
_GIT_DEFAULTS: Final = frozenset({".git/hooks", ".git/hooks/"})
HOOKS_PATH_NOTE: Final = (
    "git hooks: core.hooksPath is {current!r}, so the hub's .githooks do not run; "
    "run git config core.hooksPath .githooks to use them"
)


class HooksPath(StrEnum):
    """What to do with the hub's ``core.hooksPath``."""

    SET = "set"
    KEEP = "keep"
    FOREIGN = "foreign"


def hooks_path_action(current: str | None) -> HooksPath:
    """``SET``: unset or git's default; ``KEEP``: already ``.githooks``; else ``FOREIGN``."""
    if current is None or current.strip() in _GIT_DEFAULTS or not current.strip():
        return HooksPath.SET
    if current.strip().rstrip("/") == GIT_HOOKS_FOLDER:
        return HooksPath.KEEP
    return HooksPath.FOREIGN
