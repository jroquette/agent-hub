"""Run an acceptance criterion's check from the web (playground): "Run check" on the AC card.

The browser names the criterion, never the command: the command is the one ``features.json``
records for that AC (``AcRow.command``), read here through the hub read models. A manual AC, or
one with no command, is refused (409). The command runs with ``/bin/sh -c`` in the checkout of
the AC's repo (``<hub>/../<repo dir>``; with no repo on the AC, the project's only repo), stdin
empty, stdout and stderr merged, with this process's environment minus ``LINEAR_API_KEY``. It
runs in its own process group, which is killed at the timeout; its output is then read for
``DRAIN_SECONDS`` at most (a process that left the group may hold the pipe open). The answer
carries the exit code, the duration, the checkout's branch and short commit, and the output, its
tail kept when it is longer than ``MAX_OUTPUT_BYTES``.

Nothing is recorded: the run proves nothing to the hub (that is ``/evaluate``'s evidence); it
only lets the owner see the check pass or fail. The route is a run write: it needs the session
cookie and this server's own Origin (``local_security.RUN_WRITES``).
"""

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from agent_hub.api.rfc9457 import Problem
from agent_hub.core.readmodels.read_ports import HubReadModels

TIMEOUT_SECONDS: Final = 600
DRAIN_SECONDS: Final = 5
MAX_OUTPUT_BYTES: Final = 200_000
HIDDEN_VARIABLES: Final = frozenset({"LINEAR_API_KEY"})
SHELL: Final = "/bin/sh"


class AcCheckRun(BaseModel):
    """One run of an AC's check: what ran, where, and what it answered."""

    model_config = ConfigDict(frozen=True)

    ac: str
    command: str
    repo: str
    branch: str | None
    commit: str | None
    exit_code: int | None
    passed: bool
    timed_out: bool
    duration_ms: int
    output: str
    truncated: bool


class AcCheckError(Exception):
    """The check cannot run (unknown AC, no command, manual step, no checkout)."""

    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail


def ac_check_problem(error: Any) -> Problem:
    """``AcCheckError``: its own status, title and detail."""
    return Problem(error.status, error.title, error.detail)


class AcCheckRunner:
    """Runs the recorded check of one acceptance criterion in its repo's checkout."""

    def __init__(self, models: HubReadModels, *, timeout: float = TIMEOUT_SECONDS) -> None:
        self._models = models
        self._timeout = timeout

    def run(self, project: str, slug: str, ac_id: str) -> AcCheckRun:
        """Run AC ``ac_id``'s command and answer its result (never raises on a failing check)."""
        detail = self._models.get_feature(project, slug)
        ac = next((row for row in detail.ac_rows if row.id == ac_id), None)
        if ac is None:
            raise AcCheckError(404, "Unknown acceptance criterion", f"{slug} has no {ac_id}.")
        if ac.manual:
            raise AcCheckError(409, "Manual owner step", f"{ac_id} is checked by hand.")
        if not ac.command:
            raise AcCheckError(409, "No check recorded", f"{ac_id} records no command.")
        repo, cwd = self._checkout(project, ac.repo)
        branch, commit = _git_head(cwd)
        started = time.monotonic()
        output, code, timed_out = self._execute(ac.command, cwd)
        duration = int((time.monotonic() - started) * 1000)
        truncated = len(output) > MAX_OUTPUT_BYTES
        text = output[-MAX_OUTPUT_BYTES:].decode("utf-8", errors="replace")
        return AcCheckRun(
            ac=ac.id,
            command=ac.command,
            repo=repo,
            branch=branch,
            commit=commit,
            exit_code=code,
            passed=code == 0 and not timed_out,
            timed_out=timed_out,
            duration_ms=duration,
            output=text,
            truncated=truncated,
        )

    def _checkout(self, project: str, repo: str | None) -> tuple[str, Path]:
        repos = self._models.project_repos(project).items
        hub = Path(self._models.get_project(project).hub_path)
        if repo is None and len(repos) != 1:
            raise AcCheckError(
                409, "Repo unknown", "The AC names no repo and the project has several."
            )
        wanted = (repo or repos[0].dir).lower()
        found = next((r for r in repos if wanted in (r.name.lower(), r.dir.lower())), None)
        if found is None:
            raise AcCheckError(409, "Repo unknown", f"The project has no repo {repo}.")
        cwd = (hub.parent / found.dir).resolve()
        if not cwd.is_dir():
            raise AcCheckError(
                409, "No checkout", f"{found.dir} is not checked out beside the hub."
            )
        return found.dir, cwd

    def _execute(self, command: str, cwd: Path) -> tuple[bytes, int | None, bool]:
        env = {k: v for k, v in os.environ.items() if k not in HIDDEN_VARIABLES}
        child = subprocess.Popen(  # noqa: S603 -- the command is the hub's own record, not input
            [SHELL, "-c", command],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            output, _ = child.communicate(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            return _drain(child), None, True
        return output, child.returncode, False


def _drain(child: subprocess.Popen[bytes]) -> bytes:
    """The output of a killed check, read for ``DRAIN_SECONDS`` at most.

    A process that left the check's group can hold the pipe open after the kill: past the bound
    the pipe is closed and the output read so far is the answer.
    """
    try:
        output, _ = child.communicate(timeout=DRAIN_SECONDS)
    except subprocess.TimeoutExpired as error:
        output = error.output or b""
        if child.stdout is not None:
            child.stdout.close()
        child.wait()
    return output


def _git_head(cwd: Path) -> tuple[str | None, str | None]:
    """The checkout's branch and short commit, None for each one git cannot tell."""

    def ask(*args: str) -> str | None:
        try:
            done = subprocess.run(  # noqa: S603 -- a fixed git argv
                ["git", *args],  # noqa: S607 -- git from PATH, as the CLI uses it
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired:
            return None
        out = done.stdout.strip()
        return out if done.returncode == 0 and out else None

    branch = ask("rev-parse", "--abbrev-ref", "HEAD")
    return (None if branch == "HEAD" else branch), ask("rev-parse", "--short", "HEAD")
