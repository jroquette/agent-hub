"""Runs ``git`` and ``gh`` for one learning action under one deadline (ADR 0024).

Every child gets an argv list (never a shell), an empty stdin, no terminal prompt and the
caller's environment without git's location variables, so nothing but its cwd says which
repository it acts on. stderr is discarded; stdout is read back (at most ``OUTPUT_LIMIT`` bytes)
only for the caller to parse and is never logged or put in an error. A child runs in a session
of its own, so the deadline kills it and every process it started (a credential helper, ssh).
"""

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, NamedTuple, Protocol

from agent_hub.core.learnings.brain_change_requests import (
    ChangeRequestFailedError,
    ChangeRequestTimeoutError,
)
from agent_hub.hub_git.refspec_guard import push_argv

# One deadline for every git and gh step of an action (plan "Inputs, bounds and budget").
ACTION_SECONDS: Final = 60.0
OUTPUT_LIMIT: Final = 1_048_576
# Git's repository-local variables (``git rev-parse --local-env-vars``) except the GIT_CONFIG*
# ones: each would point git at another repository, index or object store than its cwd's.
GIT_LOCATION_VARIABLES: Final = (
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
# No prompt can wait for an answer that never comes; paths are paths, never patterns.
_QUIET: Final = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GH_PROMPT_DISABLED": "1",
    "GH_NO_UPDATE_NOTIFIER": "1",
    "GIT_LITERAL_PATHSPECS": "1",
}


class ProcessResult(NamedTuple):
    """A finished child: its exit code and the start of its stdout (empty when not kept)."""

    returncode: int
    stdout: bytes


class Launch(Protocol):
    """Starts one child and waits for it; ``TimeoutError`` once ``timeout`` passes (child
    killed), ``OSError`` when it cannot start."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        keep_stdout: bool,
    ) -> ProcessResult:
        """Run ``argv``."""
        ...


def child_env(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` without git's location variables, with prompts off and literal pathspecs."""
    env = {name: value for name, value in environ.items() if name not in GIT_LOCATION_VARIABLES}
    return env | _QUIET


def run_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    keep_stdout: bool,
) -> ProcessResult:
    """Run ``argv`` in ``cwd`` with exactly ``env`` in a session of its own (``Launch``)."""
    with contextlib.ExitStack() as stack:
        out = stack.enter_context(tempfile.TemporaryFile()) if keep_stdout else None
        child = stack.enter_context(
            subprocess.Popen(  # noqa: S603 - an argv list, never a shell; the tool is git or gh
                list(argv),
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=out if out is not None else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        )
        try:
            returncode = child.wait(timeout=timeout)
        except BaseException:
            _kill_group(child)
            raise
        if out is None:
            return ProcessResult(returncode=returncode, stdout=b"")
        out.seek(0)
        return ProcessResult(returncode=returncode, stdout=out.read(OUTPUT_LIMIT))
    raise AssertionError  # pragma: no cover - ExitStack never swallows the return


def _kill_group(child: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signal.SIGKILL)
    child.wait()


class Deadline:
    """A point in time ``seconds`` from now; ``remaining`` raises once it has passed."""

    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + seconds

    def remaining(self) -> float:
        """Seconds left; ``ChangeRequestTimeoutError`` when none are."""
        left = self._end - self._clock()
        if left <= 0:
            raise ChangeRequestTimeoutError
        return left


class GitSession:
    """The git and gh steps of one action, all under one ``Deadline``."""

    def __init__(self, runner: GitRunner, deadline: Deadline) -> None:
        self._runner = runner
        self._deadline = deadline

    def git(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        step: str,
        extra_env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> ProcessResult:
        """Run ``git <args>``; ``ChangeRequestFailedError(step)`` on a non-zero exit when
        ``check``, ``ChangeRequestTimeoutError`` past the deadline."""
        return self._run(
            self._runner.git_name, args, cwd=cwd, step=step, env=extra_env, check=check
        )

    def gh(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        step: str,
        keep_stdout: bool = True,
        check: bool = True,
    ) -> ProcessResult:
        """Run ``gh <args>`` as ``git`` runs; with ``keep_stdout=False`` its stdout is never read
        (``gh auth token`` prints a secret)."""
        tool = self._runner.gh_name
        return self._run(tool, args, cwd=cwd, step=step, check=check, keep=keep_stdout)

    def push(
        self, branch: str, *, cwd: Path, default_branch: str, prefix: str, delete: bool = False
    ) -> None:
        """Push (or delete) one learning branch on ``origin``; the guard runs before git."""
        args = push_argv(branch, default_branch=default_branch, prefix=prefix, delete=delete)
        self.git(args, cwd=cwd, step="delete branch" if delete else "push")

    def _run(
        self,
        tool: str,
        args: Sequence[str],
        *,
        cwd: Path,
        step: str,
        env: Mapping[str, str] | None = None,
        check: bool = True,
        keep: bool = True,
    ) -> ProcessResult:
        timeout = self._deadline.remaining()
        program = self._runner.program(tool)
        if program is None:
            raise ChangeRequestFailedError(step=step)
        try:
            result = self._runner.launch(
                [program, *args],
                cwd=cwd,
                env=self._runner.env | dict(env or {}),
                timeout=timeout,
                keep_stdout=keep,
            )
        except subprocess.TimeoutExpired, TimeoutError:
            raise ChangeRequestTimeoutError from None
        except OSError:
            raise ChangeRequestFailedError(step=step) from None
        if check and result.returncode != 0:
            raise ChangeRequestFailedError(step=step)
        return result


class GitRunner:
    """Where ``git`` and ``gh`` are and the environment they get; ``start`` begins an action."""

    def __init__(
        self,
        *,
        git: str = "git",
        gh: str = "gh",
        deadline: float = ACTION_SECONDS,
        environ: Mapping[str, str] | None = None,
        launch: Launch = run_process,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.git_name = git
        self.gh_name = gh
        self.deadline = deadline
        self.environ = dict(os.environ if environ is None else environ)
        self.env = child_env(self.environ)
        self.launch = launch
        self._clock = clock

    def program(self, tool: str) -> str | None:
        """``tool`` as an absolute path found on the children's ``PATH``, or None."""
        found = shutil.which(tool, path=self.env.get("PATH") or "")
        return None if found is None else os.path.abspath(found)

    def start(self, *, seconds: float | None = None) -> GitSession:
        """A session whose steps share one deadline (``deadline`` seconds unless given)."""
        budget = self.deadline if seconds is None else seconds
        return GitSession(self, Deadline(budget, clock=self._clock))
