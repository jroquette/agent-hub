"""Runs a tool as a child process (no shell) and returns its exit code and both streams.

The hub commands run git, and later ``gh``, through this one runner. A call with a timeout runs
in a new session, so a timeout (or any interruption) kills the child and every process it
started: a grandchild left running would hold the output pipes open and the read would never
end. A call without a timeout stays in the caller's process group, so Ctrl-C reaches the tool.
"""

import contextlib
import os
import signal
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, NamedTuple

from agent_hub.cli.errors import ChildTimedOutError

# Git's repository-local variables (``git rev-parse --local-env-vars``) except the GIT_CONFIG*
# ones. Set by the caller (a git hook, a worktree script), each would point git at another repo,
# index or object store than the one the command names with its cwd.
GIT_LOCATION_VARIABLES = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)
_OPTIONAL_LOCKS_VARIABLE = "GIT_OPTIONAL_LOCKS"


class ChildResult(NamedTuple):
    """What a finished child left: its exit code and the bytes of each stream."""

    returncode: int
    stdout: bytes
    stderr: bytes


def run_child(
    argv: Sequence[str],
    *,
    cwd: Path | str,
    env: Mapping[str, str],
    timeout: float | None,
    own_session: bool | None = None,
    output_limit: int | None = None,
) -> ChildResult:
    """Run ``argv`` in ``cwd`` with exactly ``env``; stdin is empty, both streams are captured.

    With ``own_session`` (by default: when there is a ``timeout``) the child runs in a new session
    and a timeout kills its whole group; without it, the child stays in the caller's group, where
    the caller's own killer reaches it and what it started, and a timeout kills the child alone.

    With ``output_limit``, each stream goes to a temporary file and only its last
    ``output_limit`` bytes are read back: the memory a chatty child costs is bounded, and a
    process it leaves behind holds no pipe the read would wait on.

    Raises ``ChildTimedOutError`` after ``timeout`` seconds, and ``OSError`` (for example
    ``FileNotFoundError``) when the tool cannot start.
    """
    new_session = timeout is not None if own_session is None else own_session
    if output_limit is not None:
        return _run_to_files(
            argv, cwd=cwd, env=env, timeout=timeout, new_session=new_session, limit=output_limit
        )
    with subprocess.Popen(  # noqa: S603 - an argv list, never a shell; callers pass the tool
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=new_session,
    ) as child:
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(child, group=new_session)
            raise ChildTimedOutError(program=argv[0], timeout=timeout or 0.0) from None
        except BaseException:
            _kill(child, group=new_session)
            raise
    return ChildResult(returncode=child.returncode, stdout=stdout, stderr=stderr)


def _run_to_files(
    argv: Sequence[str],
    *,
    cwd: Path | str,
    env: Mapping[str, str],
    timeout: float | None,
    new_session: bool,
    limit: int,
) -> ChildResult:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        with subprocess.Popen(  # noqa: S603 - an argv list, never a shell; callers pass the tool
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=new_session,
        ) as child:
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill(child, group=new_session)
                raise ChildTimedOutError(program=argv[0], timeout=timeout or 0.0) from None
            except BaseException:
                _kill(child, group=new_session)
                raise
        return ChildResult(child.returncode, _tail(stdout, limit), _tail(stderr, limit))


def _tail(file: IO[bytes], limit: int) -> bytes:
    size = file.seek(0, os.SEEK_END)
    file.seek(max(0, size - limit))
    return file.read()


def stream_child(
    argv: Sequence[str],
    *,
    cwd: Path | str,
    env: Mapping[str, str],
    on_line: Callable[[bytes], None],
) -> int:
    """Run ``argv`` in ``cwd`` with exactly ``env``, hand each stdout line to ``on_line``.

    For a script the user may watch (a worktree setup that installs dependencies): no timeout,
    the caller's process group, stdin and stderr. Returns the exit code; raises ``OSError`` when
    the script cannot start.
    """
    with subprocess.Popen(  # noqa: S603 - an argv list, never a shell; callers pass the script
        list(argv), cwd=cwd, env=dict(env), stdout=subprocess.PIPE
    ) as child:
        for line in child.stdout or ():
            on_line(line)
    return child.returncode


def git_env(environ: Mapping[str, str], *, optional_locks: bool) -> dict[str, str]:
    """A copy of ``environ`` for git: the location variables dropped, so the cwd names the repo.

    Without ``optional_locks``, git takes no optional lock (``GIT_OPTIONAL_LOCKS=0``), so a read
    such as ``git status`` never contends with the user's own git commands.
    """
    env = {name: value for name, value in environ.items() if name not in GIT_LOCATION_VARIABLES}
    if not optional_locks:
        env[_OPTIONAL_LOCKS_VARIABLE] = "0"
    return env


def _kill(child: subprocess.Popen[bytes], *, group: bool) -> None:
    with contextlib.suppress(ProcessLookupError):
        if group:
            os.killpg(child.pid, signal.SIGKILL)
        else:
            child.kill()
