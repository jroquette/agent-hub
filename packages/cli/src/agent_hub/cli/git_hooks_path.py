"""Point the hub's git at its managed hooks: ``core.hooksPath = .githooks`` (ADR 0061).

``hub sync`` calls it after it writes the hub: git's local config of the hub folder is read and,
when ``hooks_path_action`` says so, set. Git runs in the hub folder with the location variables
dropped, so the cwd names the repository. A folder that is no git repository, or a git that
cannot run, gets a note and nothing else: the hooks are a convenience of the checkout, CI checks
the same rules.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from agent_hub.cli.child_process import ChildResult, git_env, run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.core.hub_files.git_hooks import (
    GIT_HOOKS_FOLDER,
    HOOKS_PATH_KEY,
    HOOKS_PATH_NOTE,
    HooksPath,
    hooks_path_action,
)

GIT_TIMEOUT: Final = 20
# ``git config --get`` exits 1 when the key is unset.
_UNSET: Final = 1
SET_LINE: Final = f"git hooks: core.hooksPath set to {GIT_HOOKS_FOLDER}"
NOT_SET: Final = (
    "git hooks: core.hooksPath not set ({reason}); run git config core.hooksPath {folder}"
)


def enable_git_hooks(root: Path, *, environ: Mapping[str, str]) -> tuple[str | None, str | None]:
    """``(stdout line, stderr note)``: the line when it set the key, the note when it could not
    or left another value; ``(None, None)`` when it was already ``.githooks``."""
    env = git_env(environ, optional_locks=False) | {"GIT_TERMINAL_PROMPT": "0"}
    if not os.path.lexists(root / ".git"):
        return None, None
    try:
        current = _git(root, env, "config", "--local", "--get", HOOKS_PATH_KEY)
        if current.returncode not in {0, _UNSET}:
            return None, _not_set(current.stderr)
        value = current.stdout.decode(errors="replace").strip() if current.returncode == 0 else None
        action = hooks_path_action(value)
        if action is HooksPath.KEEP:
            return None, None
        if action is HooksPath.FOREIGN:
            return None, HOOKS_PATH_NOTE.format(current=value)
        written = _git(root, env, "config", "--local", HOOKS_PATH_KEY, GIT_HOOKS_FOLDER)
    except (ChildTimedOutError, OSError) as error:
        return None, _not_set(str(error).encode())
    if written.returncode != 0:
        return None, _not_set(written.stderr)
    return SET_LINE, None


def _git(root: Path, env: Mapping[str, str], *arguments: str) -> ChildResult:
    return run_child(["git", *arguments], cwd=root, env=env, timeout=GIT_TIMEOUT)


def _not_set(stderr: bytes) -> str:
    lines = [line.strip() for line in stderr.decode(errors="replace").splitlines()]
    reason = next((line for line in lines if line), "git failed")
    return NOT_SET.format(reason=reason, folder=GIT_HOOKS_FOLDER)
