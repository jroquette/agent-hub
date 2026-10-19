"""Ask git one question about a checkout: its exit code and stdout, or ``None`` when it cannot
answer (missing, failing to start, too slow).

Git runs as an absolute executable with ``core.fsmonitor`` off (no project hook runs), without the
caller's location variables (``doctor_tree.SCRUBBED_VARIABLES``), with ``GIT_OPTIONAL_LOCKS=0`` (it
never refreshes the index), in a session of its own that is killed on the way out, and with a
timeout, as ``doctor_tree`` runs it. An exit code other than 0 is an answer, not an error: the
caller says what it means (``git check-ignore`` exits 1 for a file it does not ignore).
"""

import contextlib
import os
import shutil
import signal
import subprocess
from collections.abc import Sequence
from pathlib import Path

from agent_hub.generator.doctor_tree import GIT_TIMEOUT_SECONDS, SCRUBBED_VARIABLES


def git_answer(arguments: Sequence[str], *, cwd: Path) -> tuple[int, bytes] | None:
    """Git's exit code and stdout for ``arguments`` run in ``cwd``, or ``None``."""
    found = shutil.which("git")
    if found is None:
        return None
    environment = {
        name: value for name, value in os.environ.items() if name not in SCRUBBED_VARIABLES
    }
    try:
        with subprocess.Popen(  # noqa: S603 - absolute git, fixed argv, no shell
            [os.path.abspath(found), "-c", "core.fsmonitor=false", *arguments],
            cwd=cwd,
            env={**environment, "GIT_OPTIONAL_LOCKS": "0"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        ) as child:
            try:
                output, _ = child.communicate(timeout=GIT_TIMEOUT_SECONDS)
            finally:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(child.pid, signal.SIGKILL)
    except subprocess.TimeoutExpired, OSError:
        return None
    return child.returncode, output
