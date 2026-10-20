"""The one way the generator runs git: as an absolute executable with ``core.fsmonitor`` off (no
project hook runs), without the caller's location variables (``SCRUBBED_VARIABLES``), with
``GIT_OPTIONAL_LOCKS=0`` (it never refreshes the index), in a session of its own that is killed on
the way out, and with a timeout.

``run_git`` is the runner ``doctor_tree`` lists a tree with: it raises ``GitRunError`` when git
cannot start or runs too long. ``git_answer`` asks one question: an exit code other than 0 is an
answer, not an error (``git check-ignore`` exits 1 for a file it does not ignore), and ``None``
means git could not answer (missing, failing to start, too slow).
"""

import contextlib
import os
import shutil
import signal
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from agent_hub.generator.errors import GeneratorError

GIT_TIMEOUT_SECONDS = 10.0
# Git's repository-local variables (``git rev-parse --local-env-vars``, git 2.43): each makes
# git read another repository, index, config or work tree than the tree's own.
SCRUBBED_VARIABLES: Final = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
)


class GitRunError(GeneratorError):
    """Why git could not run to its end, as one line."""


def run_git(
    executable: str, arguments: Sequence[str], *, cwd: Path, timeout: float
) -> tuple[int, bytes, bytes]:
    """Git's exit code, stdout and stderr for ``arguments`` run in ``cwd``; raises
    ``GitRunError`` when it cannot start or runs longer than ``timeout`` seconds."""
    try:
        with subprocess.Popen(  # noqa: S603 - absolute git, fixed argv, no shell
            [executable, "-c", "core.fsmonitor=false", *arguments],
            cwd=cwd,
            env=_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as child:
            try:
                output, errors = child.communicate(timeout=timeout)
            finally:
                # Whatever happened, no child git started is left running or holding the pipes.
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(child.pid, signal.SIGKILL)
    except subprocess.TimeoutExpired as error:
        raise GitRunError(f"git timed out after {timeout:g} s") from error
    except OSError as error:
        raise GitRunError(f"git could not run: {error.strerror or error}") from error
    return child.returncode, output, errors


def git_answer(arguments: Sequence[str], *, cwd: Path) -> tuple[int, bytes] | None:
    """Git's exit code and stdout for ``arguments`` run in ``cwd``, or ``None``."""
    found = shutil.which("git")
    if found is None:
        return None
    try:
        returncode, output, _ = run_git(
            os.path.abspath(found), arguments, cwd=cwd, timeout=GIT_TIMEOUT_SECONDS
        )
    except GitRunError:
        return None
    return returncode, output


def _git_environment() -> dict[str, str]:
    kept = {name: value for name, value in os.environ.items() if name not in SCRUBBED_VARIABLES}
    return {**kept, "GIT_OPTIONAL_LOCKS": "0"}
