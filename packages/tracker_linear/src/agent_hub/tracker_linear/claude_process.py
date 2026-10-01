"""Runs ``claude -p`` for the Linear MCP adapter, in the caller's process group (E8, D9).

The child stays in the caller's process group, so the caller's own killer (Ctrl-C, a
supervisor's group kill) reaches it and what it starts. A timeout kills the child alone and
does not wait for its output pipes to close: a grandchild it started may survive and hold
them, and only the caller's group kill reaches it.

``claude`` is resolved on the child environment's ``PATH``, never the caller's, so the
environment a call is given decides which ``claude`` runs.
"""

import contextlib
import errno
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

CLAUDE_PROGRAM = "claude"


class ClaudeOutput(NamedTuple):
    """What a finished ``claude`` left: its exit code and the bytes of each stream."""

    returncode: int
    stdout: bytes
    stderr: bytes


def run_claude(
    argv: Sequence[str], *, cwd: Path | str, env: Mapping[str, str], timeout_s: float
) -> ClaudeOutput:
    """Run ``argv`` in ``cwd`` with exactly ``env``; stdin is empty, both streams are captured.

    ``argv[0]`` is looked up on ``env``'s ``PATH`` (an absent or empty one finds nothing) and
    made absolute.
    Raises ``FileNotFoundError`` when it is not there, and ``TimeoutError`` after
    ``timeout_s`` seconds, once the child is killed.
    """
    program = shutil.which(argv[0], path=env.get("PATH") or "")
    if program is None:
        raise FileNotFoundError(errno.ENOENT, f"{argv[0]} is not on PATH", argv[0])
    # A relative PATH entry is found from the caller's cwd; the child starts in ``cwd``.
    program = os.path.abspath(program)
    with (
        subprocess.Popen(  # noqa: S603 - an argv list, never a shell; the tool is claude
            [program, *argv[1:]],
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=False,
        ) as child
    ):
        try:
            stdout, stderr = child.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill(child)
            raise TimeoutError(f"{argv[0]} timed out after {timeout_s:g} s") from None
        except BaseException:
            _kill(child)
            raise
    return ClaudeOutput(returncode=child.returncode, stdout=stdout, stderr=stderr)


def _kill(child: subprocess.Popen[bytes]) -> None:
    """Kill the child and reap it, so no zombie is left even when the caller is interrupted."""
    with contextlib.suppress(ProcessLookupError):
        child.kill()
    child.wait()
