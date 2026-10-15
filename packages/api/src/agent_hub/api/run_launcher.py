"""``ProcessRunLauncher``: hub web's workflow runs as ``hub workflow run`` children (ADR 0032).

The program is this interpreter's own hub (``python -I -m agent_hub.cli``), the release that
serves the web, never a ``hub`` found on ``PATH``; the api never imports cli. Every call is an
argv list in the hub folder, with this process's environment minus ``LINEAR_API_KEY`` (the
generic run makes no tracker write), plus ``AGENT_HUB_ROOT`` (the hub) and ``AGENT_HUB_DB`` (the
web's store, absolute), so the child's events, appended through its ``IngestEvents``, are the
ones the web reads. A start (always ``--live``) or resume is detached: its own session (its
group id is its pid), stdin empty, both streams appended to ``.agent-runs/web/<run>.log``. Its
pid file ``.agent-runs/web/<run>.pid`` is made before the child (``O_EXCL``, 0600, never
through a link) and holds the pid, its start time and the issue. One lock covers the in-use
check, the spawn and the registration, so of two concurrent launches of a run one answers 409;
at most ``max_children`` children run at once.

A child is ours while this process holds it unreaped: a pipe only the child holds tells the
reaper it ended, and the pid file goes before the child is reaped, so its pid (its group's id)
cannot be reused under a signal. A pid file of an earlier ``hub web`` is ``ours`` while its
process has the recorded start time (``/proc`` on Linux, else ``ps``), ``stale`` when the
process is gone or started at another time (the file is then removed), else ``unknown``: never
signalled, never removed, and counted live. Cancel sends SIGINT to the group (the CLI then kills
its node children), SIGKILL after ``grace`` seconds, then abandons the run so its end is
recorded. Abandon waits for the CLI. Nothing here polls a run's status: it comes from events.
"""

import contextlib
import fcntl
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.launch import (
    RUN_ID_PATTERN,
    LaunchSpec,
    RunConflictError,
    RunLaunchError,
)

WEB_RUNS: Final = Path(".agent-runs", "web")
RUN_FOLDERS: Final = Path(".agent-runs", "workflows")
HIDDEN_VARIABLES: Final = frozenset({"LINEAR_API_KEY"})
PRIVATE_MODE: Final = 0o600
_NEW_FILE: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_LOG_FILE: Final = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_PID_FILE_BYTES: Final = 4096
MAX_PID_FILES: Final = 64
MAX_CHILDREN: Final = 8
ABANDON_TIMEOUT_SECONDS: Final = 60.0
GRACE_SECONDS: Final = 10.0
_POLL_SECONDS: Final = 0.2
LOGGER = logging.getLogger("agent_hub.api")

type PidState = Literal["ours", "stale", "unknown"]


def own_hub_program() -> tuple[str, ...]:
    """This hub, by absolute path; ``-I`` keeps the cwd and ``PYTHON*`` off the module path."""
    return (sys.executable, "-I", "-m", "agent_hub.cli")


def process_started(pid: int) -> str | None:
    """When ``pid`` started (``/proc`` on Linux, else ``ps``), or None when unknown."""
    with contextlib.suppress(OSError, IndexError):
        stat_line = Path(f"/proc/{pid}/stat").read_text(encoding="latin-1")
        return stat_line.rsplit(")", 1)[1].split()[19]
    ps = shutil.which("ps", path="/bin:/usr/bin")
    if ps is None or Path("/proc/self").exists():
        return None
    try:
        done = subprocess.run(  # noqa: S603 -- an argv list of a fixed program
            [ps, "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            env={"LC_ALL": "C", "PATH": "/bin:/usr/bin"},
            timeout=5,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    started = done.stdout.decode(errors="replace").strip()
    return started if done.returncode == 0 and started else None


def input_text(value: JsonValue) -> str:
    """An input as ``--input`` takes it: ``true``/``false``, a number, or the text itself."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


@dataclass
class _Child:
    """A child this process started and has not reaped; ``ended`` once its pipe closed."""

    process: subprocess.Popen[bytes]
    issue: str | None
    ended_read: int
    ended: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True)
class _PidFile:
    pid: int
    started: str
    issue: str | None


class ProcessRunLauncher:
    """``RunLauncher`` over ``hub workflow run`` children."""

    def __init__(  # noqa: PLR0913 -- the launcher's settings, all keyword-only
        self,
        *,
        db_path: Path,
        environ: Mapping[str, str],
        program: Sequence[str] | None = None,
        started_of: Callable[[int], str | None] = process_started,
        grace: float = GRACE_SECONDS,
        max_children: int = MAX_CHILDREN,
    ) -> None:
        self._db_path = db_path.resolve()
        self._environ = environ
        self._program = tuple(program or own_hub_program())
        self._started_of = started_of
        self._grace = grace
        self._max_children = max_children
        self._guard = threading.Lock()
        self._children: dict[Path, _Child] = {}

    def start(self, spec: LaunchSpec) -> None:
        argv = [*self._program, "workflow", "run", spec.workflow, "--run-id", spec.run_id]
        argv.append("--live")
        for name, value in spec.inputs.items():
            argv += ["--input", f"{name}={input_text(value)}"]
        self._detach(spec.hub_path, spec.run_id, argv, issue=spec.issue)

    def resume(self, hub_path: str, run_id: str, *, issue: str | None) -> None:
        argv = [*self._program, "workflow", "run", "--resume", run_id]
        self._detach(hub_path, run_id, argv, issue=issue, probe=True)

    def abandon(self, hub_path: str, run_id: str) -> None:
        argv = [*self._program, "workflow", "run", "--abandon", run_id]
        try:
            done = subprocess.run(  # noqa: S603 -- an argv list; the program is this hub
                argv,
                cwd=hub_path,
                env=self._env(hub_path),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=ABANDON_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RunLaunchError(
                f"hub workflow run --abandon did not finish: {type(error).__name__}"
            ) from None
        if done.returncode != 0:
            # Not the CLI's words: its stderr can name local paths.
            reason = "hub workflow run refused to abandon the run (it may be in use or ended)"
            raise RunConflictError(code="refused", reason=reason, run_id=run_id)

    def cancel(self, hub_path: str, run_id: str) -> bool:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            return False
        folder = _existing_folder(Path(hub_path))
        if folder is None:
            return False
        pid_path = folder / f"{run_id}.pid"
        with self._guard:
            child = self._children.get(pid_path)
            if child is not None:
                _signal_group(child.process.pid, signal.SIGINT)
        if child is not None:
            pid, alive = child.process.pid, _not_set(child.ended)
        else:
            record = _read_pid_file(pid_path)
            if record is None or self._state(record) != "ours":
                return False
            pid, alive = record.pid, self._still(record)
            _signal_group(pid, signal.SIGINT)
        stop = threading.Thread(
            target=self._finish_cancel,
            args=(hub_path, run_id),
            kwargs={"pid": pid, "alive": alive},
            daemon=True,
        )
        stop.start()
        return True

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]:
        folder = _existing_folder(Path(hub_path))
        if folder is None:
            return {}
        with self._guard:
            live = {
                path.stem: child.issue
                for path, child in self._children.items()
                if path.parent == folder
            }
            for path, record in _pid_files(folder):
                if path.stem in live:
                    continue
                state = self._state(record)
                if state == "stale":
                    path.unlink(missing_ok=True)
                else:
                    live[path.stem] = record.issue
        return live

    def _finish_cancel(
        self, hub_path: str, run_id: str, *, pid: int, alive: Callable[[], bool]
    ) -> None:
        deadline = time.monotonic() + self._grace
        while alive() and time.monotonic() < deadline:
            time.sleep(_POLL_SECONDS)
        with self._guard:
            if alive():
                _signal_group(pid, signal.SIGKILL)
        deadline = time.monotonic() + self._grace
        while alive() and time.monotonic() < deadline:
            time.sleep(_POLL_SECONDS)
        try:
            self.abandon(hub_path, run_id)
        except (RunConflictError, RunLaunchError) as error:
            LOGGER.warning(
                "abandon after cancel failed",
                extra={"run_id": run_id, "error_type": type(error).__name__},
            )

    def _state(self, record: _PidFile) -> PidState:
        """Whether a pid file of an earlier ``hub web`` names its own process still."""
        started = self._started_of(record.pid)
        if started is not None:
            return "ours" if record.started and started == record.started else "stale"
        try:
            os.kill(record.pid, 0)
        except ProcessLookupError:
            return "stale"
        except PermissionError:
            return "unknown"
        return "unknown"

    def _still(self, record: _PidFile) -> Callable[[], bool]:
        return lambda: self._state(record) == "ours"

    def _env(self, hub_path: str) -> dict[str, str]:
        env = {k: v for k, v in self._environ.items() if k not in HIDDEN_VARIABLES}
        return env | {"AGENT_HUB_ROOT": hub_path, "AGENT_HUB_DB": str(self._db_path)}

    def _detach(
        self,
        hub_path: str,
        run_id: str,
        argv: list[str],
        *,
        issue: str | None,
        probe: bool = False,
    ) -> None:
        folder = _web_folder(Path(hub_path))
        pid_path = folder / f"{run_id}.pid"
        with self._guard:
            self._refuse_busy(pid_path, run_id)
            if probe:
                _probe_run_lock(Path(hub_path), run_id)
            if len(self._children) >= self._max_children:
                reason = f"{self._max_children} runs started from hub web are still running"
                raise RunConflictError(code="too_many_runs", reason=reason)
            # Nothing live is named by it (checked above): a stale file, a link or junk.
            pid_path.unlink(missing_ok=True)
            child = self._spawn_registered(hub_path, pid_path, argv, issue=issue)
        threading.Thread(target=self._reap, args=(pid_path, child), daemon=True).start()

    def _refuse_busy(self, pid_path: Path, run_id: str) -> None:
        busy = pid_path in self._children
        record = _read_pid_file(pid_path)
        if busy or (record is not None and self._state(record) != "stale"):
            reason = "the run's child is still running"
            raise RunConflictError(code="in_use", reason=reason, run_id=run_id)

    def _spawn_registered(
        self, hub_path: str, pid_path: Path, argv: list[str], *, issue: str | None
    ) -> _Child:
        try:
            pid_file = os.open(pid_path, _NEW_FILE, PRIVATE_MODE)
        except FileExistsError:
            reason = "the run's child is still running"
            raise RunConflictError(code="in_use", reason=reason) from None
        except OSError as error:
            raise RunLaunchError(f"cannot make the run's pid file: {error.strerror}") from None
        ended_read, ended_write = os.pipe()
        try:
            log_path = pid_path.with_suffix(".log")
            process = self._spawn(hub_path, log_path, argv, ended_write=ended_write)
        except BaseException:
            os.close(pid_file)
            os.close(ended_read)
            pid_path.unlink(missing_ok=True)
            raise
        finally:
            os.close(ended_write)
        started = self._started_of(process.pid) or ""
        with os.fdopen(pid_file, "w", encoding="utf-8") as file:
            json.dump({"pid": process.pid, "started": started, "issue": issue}, file)
        child = _Child(process, issue, ended_read)
        self._children[pid_path] = child
        return child

    def _reap(self, pid_path: Path, child: _Child) -> None:
        """Wait until the child's pipe closes; drop its own entry and pid file, then reap it."""
        with os.fdopen(child.ended_read, "rb") as ended:
            ended.read()
        with self._guard:
            child.ended.set()
            if self._children.get(pid_path) is child:
                del self._children[pid_path]
                pid_path.unlink(missing_ok=True)
        child.process.wait()

    def _spawn(
        self, hub_path: str, log_path: Path, argv: list[str], *, ended_write: int
    ) -> subprocess.Popen[bytes]:
        try:
            log = os.open(log_path, _LOG_FILE, PRIVATE_MODE)
        except OSError as error:
            raise RunLaunchError(f"cannot open the run's log: {error.strerror}") from None
        try:
            return subprocess.Popen(  # noqa: S603 -- an argv list; the program is this hub
                argv,
                cwd=hub_path,
                env=self._env(hub_path),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                pass_fds=(ended_write,),
            )
        except OSError as error:
            raise RunLaunchError(f"cannot start hub workflow run: {error.strerror}") from None
        finally:
            os.close(log)


def _web_folder(hub: Path) -> Path:
    """``<hub>/.agent-runs/web``, made owner-only; refused when a part of it is a link."""
    folder = hub
    for part in WEB_RUNS.parts:
        folder = folder / part
        try:
            folder.mkdir(mode=0o700, exist_ok=True)
        except OSError as error:
            raise RunLaunchError(f"cannot make {WEB_RUNS}: {error.strerror}") from None
        _refuse_link(folder)
    return folder


def _existing_folder(hub: Path) -> Path | None:
    """``<hub>/.agent-runs/web`` when it exists (None else); refused when a part is a link."""
    folder = hub
    for part in WEB_RUNS.parts:
        folder = folder / part
        if not folder.is_symlink() and not folder.exists():
            return None
        _refuse_link(folder)
    return folder


def _refuse_link(folder: Path) -> None:
    if folder.is_symlink() or not folder.is_dir():
        raise RunLaunchError(f"{WEB_RUNS} is not a folder of the hub; nothing was done")


def _pid_files(folder: Path) -> Iterator[tuple[Path, _PidFile]]:
    """The first ``MAX_PID_FILES`` pid files that read, by name."""
    try:
        paths = sorted(folder.glob("*.pid"))[:MAX_PID_FILES]
    except OSError:
        return
    for path in paths:
        record = _read_pid_file(path)
        if record is not None:
            yield path, record


def _read_pid_file(path: Path) -> _PidFile | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as file:
            data = json.loads(file.read(MAX_PID_FILE_BYTES))
    except OSError, ValueError:
        return None
    if not isinstance(data, dict):
        return None
    pid, started, issue = data.get("pid"), data.get("started"), data.get("issue")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return None
    if not isinstance(started, str):
        return None
    return _PidFile(pid, started, issue if isinstance(issue, str) else None)


def _probe_run_lock(hub: Path, run_id: str) -> None:
    """409 ``in_use`` while another process (a CLI) holds the run's lock; never waits."""
    try:
        descriptor = os.open(
            hub / RUN_FOLDERS / run_id / "lock", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
        )
    except OSError:
        return  # no lock file yet, or not one to open: the CLI decides
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        reason = "another hub workflow run holds the run"
        raise RunConflictError(code="in_use", reason=reason, run_id=run_id) from None
    finally:
        os.close(descriptor)


def _not_set(event: threading.Event) -> Callable[[], bool]:
    return lambda: not event.is_set()


def _signal_group(pid: int, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)
