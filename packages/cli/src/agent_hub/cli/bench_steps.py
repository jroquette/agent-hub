"""The steps of ``hub bench``: read the cases, add and remove the bench worktrees, grade, run.

The cases come from the hub's ``brain/workflow/bench/tasks.json`` (absent: none, spec Q-6), read
as a regular file only, at most ``MAX_CASES_BYTES + 1`` bytes, then checked in the order of plan
E7: strict JSON, the script's unknown-repo line, each shape problem (E4); each refusal exits 1.
Excluded cases are never run.

Each worktree is a detached checkout of the case's repo under ``<ws>/_bench/wt``, where ``<ws>``
is the folder of the hub's main checkout; a leftover folder there is removed first, and the
worktree is removed when its step ends, whatever ends it (a failure, Ctrl-C). The user's own
checkout is only the repo git adds the worktree to. No child gets the tracker key or a GitHub
token (``untrusted_env``, plan E9); the case's ``env`` reaches the test command only (E17). Git
runs in the caller's process group; ``setup_cmd``, the test command and the session run the
case's code (servers, test workers), so each runs in its own session: its timeout, Ctrl-C or an
interrupted run kills its whole group. A step that fails (git, ``setup_cmd``, a test command
that cannot start or runs past its timeout) is that case's failure (``StepError``), never a
crash.

One bench at a time per workspace: ``workspace_lock_or_exit`` creates ``<ws>/_bench/bench.lock``
(``O_EXCL``, holding the pid) before any worktree and removes it at the end. A lock already
there exits 1 naming it: held by a running process, or left behind by one that ended (or with
no pid). A left-behind lock is never removed by the command, since two benches could each take
the other's lock for stale; the line tells the user to delete it.

A run is the script's: each job's worktree at the merge's parent, today's agent config from
``origin/main`` laid over it, one ``claude -p`` session sandboxed by its settings file, then the
grade. Waves of ``--parallel`` jobs start only while the budget holds (else the script's ``STOP:``
line); each record is printed and appended to ``<ws>/_bench/results/<label>.jsonl`` in job order,
then the summary is printed. A job whose worktree, setup, overlay or session cannot start (or
whose overlay checkout or reset fails) has no record: its line goes to stderr and the run exits 1
after the summary. The jobs' ``git worktree`` commands run one at a time, since git does not guard
a repo's worktree list against concurrent add, remove and prune. A session that fails without a
cost counts at ``--per-run``, as a timeout does. The settings, trace and results files are
created owner-only (0600) and never opened through a link at their path. The session gets the
sandbox's ``effortLevel`` from ``BENCH_EFFORT`` (E10) and its telemetry tags, never the case's
``env``; with ``--trace`` its stdout is kept whole in ``<results>/traces/<worktree>.jsonl`` and the
result is read from its last ``OUTPUT_LIMIT`` bytes (E15), else stdout is captured with that cap.
"""

import contextlib
import datetime
import errno
import os
import shutil
import signal
import stat
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Final

import typer

from agent_hub.cli.child_process import PRIVATE_FILE_MODE, ChildResult, run_child
from agent_hub.cli.command_exits import fail
from agent_hub.cli.errors import ChildTimedOutError, CliError
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.run_children import untrusted_env
from agent_hub.core.bench.bench_cases import (
    MAX_CASES_BYTES,
    TASKS_PATH,
    BenchCase,
    bench_cases,
    case_problems,
    read_cases,
    unknown_repo_line,
)
from agent_hub.core.bench.bench_plan import Job, stop_line, waves
from agent_hub.core.bench.bench_session import (
    AGENT_CONFIG,
    AGENT_ERROR_CHARS,
    add_worktree_argv,
    agent_argv,
    agent_outcome,
    apply_failed_outcome,
    apply_tests_argv,
    git_argv,
    grade_outcome,
    grader_argvs,
    grader_env,
    record_line,
    remove_worktree_argvs,
    result_of,
    run_record,
    sandbox_settings,
    session_env,
    settings_name,
    settings_text,
    setup_argv,
    timeout_outcome,
    validate_commits,
    validate_worktree_name,
    worktree_name,
)
from agent_hub.core.bench.bench_summary import is_expected, summary, validate_line
from agent_hub.core.doctor.bench_rule import NOT_READ
from agent_hub.core.json_form import JsonValue

BENCH_FOLDER: Final = "_bench"
WORKTREES_FOLDER: Final = "wt"
RESULTS_FOLDER: Final = "results"
TRACES_FOLDER: Final = "traces"
# The script's timeouts, in seconds.
GIT_TIMEOUT: Final = 1_800.0
SETUP_TIMEOUT: Final = 600.0
GRADER_TIMEOUT: Final = 1_800.0
AGENT_TIMEOUT: Final = 1_800.0
# A record's ``ts``: the local time, to the second (parity).
TS_FORMAT: Final = "%Y-%m-%dT%H:%M:%S"
# The overlay's source: the repo's remote default, whatever its local default branch is.
CONFIG_SOURCE: Final = "origin/main"
# The bytes kept of each stream of a child: a grade reads the last line only.
OUTPUT_LIMIT: Final = 1 << 20
LOCK_NAME: Final = "bench.lock"
_PREFIX: Final = "hub bench"
# A pid's text is short: more is no pid.
_LOCK_READ_BYTES: Final = 64
_LEFT_BEHIND_FIX: Final = "delete it if no hub bench is running in this workspace"
# ``_lock_pid``'s answer for a lock that is no regular file: never a pid (pids are above 0).
_NOT_REGULAR: Final = -1
# Opened without following a link, and without waiting on a FIFO's writer.
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class StepError(CliError):
    """A step of one case failed; the text says which step and why."""


class ChildGroups:
    """The process groups of the children running in their own session; ``stop`` kills them
    all and refuses any later one (a run's threads, interrupted)."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._live: set[int] = set()
        self._stopped = False

    @property
    def stopped(self) -> bool:
        return self._stopped

    def add(self, group: int) -> None:
        with self._guard:
            self._live.add(group)
            if self._stopped:
                _kill_group(group)

    def discard(self, group: int) -> None:
        with self._guard:
            self._live.discard(group)

    def stop(self) -> None:
        with self._guard:
            self._stopped = True
            for group in self._live:
                _kill_group(group)


def _kill_group(group: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGKILL)


@contextlib.contextmanager
def workspace_lock_or_exit(workspace: Path) -> Iterator[None]:
    """Hold ``<ws>/_bench/bench.lock`` for the block; exit 1 naming it when it is there."""
    folder = workspace / BENCH_FOLDER
    _make_folder(folder)
    lock = folder / LOCK_NAME
    ours = _link_lock_or_exit(lock)
    try:
        yield
    finally:
        # Only our own file: a lock someone replaced belongs to another bench. The pid too,
        # since a new file may reuse a freed inode number.
        with contextlib.suppress(OSError):
            found = os.lstat(lock)
            if (found.st_dev, found.st_ino) == ours and _lock_pid(lock) == os.getpid():
                lock.unlink()


def _link_lock_or_exit(lock: Path) -> tuple[int, int]:
    """Link a file already holding the pid at ``lock`` (atomic: a reader never sees it empty);
    its device and inode. Exit 1 naming the lock when one is there."""
    pid = os.getpid()
    temporary = lock.with_name(f".{LOCK_NAME}.{pid}.tmp")
    try:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        with os.fdopen(os.open(temporary, flags, 0o644), "w", encoding="ascii") as file:
            file.write(f"{pid}\n")
            created = os.fstat(file.fileno())
        os.link(temporary, lock)
    except FileExistsError:
        fail(_held_line(lock))
    except OSError as error:
        fail(f"{_PREFIX}: {lock}: {error.strerror or error}")
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()
    return created.st_dev, created.st_ino


def _held_line(lock: Path) -> str:
    pid = _lock_pid(lock)
    if pid == _NOT_REGULAR:
        return (
            f"{_PREFIX}: the lock {lock} was left behind (not a regular file): {_LEFT_BEHIND_FIX}"
        )
    if pid is None:
        return f"{_PREFIX}: the lock {lock} was left behind (no pid in it): {_LEFT_BEHIND_FIX}"
    if _is_running(pid):
        return (
            f"{_PREFIX}: another hub bench (pid {pid}) is running in this workspace;"
            f" wait for it to end (lock {lock})"
        )
    return (
        f"{_PREFIX}: the lock {lock} was left behind (pid {pid}, which is not running):"
        f" {_LEFT_BEHIND_FIX}"
    )


def _lock_pid(lock: Path) -> int | None:
    """The pid the lock holds; ``None`` without one; ``_NOT_REGULAR`` for a link, a FIFO or
    anything else not a regular file (never followed, never waited on)."""
    try:
        descriptor = os.open(lock, _OPEN_FLAGS)
    except OSError:
        return _NOT_REGULAR if os.path.islink(lock) else None
    with os.fdopen(descriptor, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            return _NOT_REGULAR
        try:
            text = file.read(_LOCK_READ_BYTES).strip()
        except OSError:
            return None
    # ASCII digits only, above 0: ``kill(0)`` would name the caller's own group.
    if not (text.isdigit() and text.isascii()) or int(text) <= 0:
        return None
    return int(text)


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OverflowError:
        return False
    return True


@dataclass(frozen=True, kw_only=True, slots=True)
class SessionPlan:
    """What every session of a run shares: its label, plugin, effort, per-run cap and trace."""

    label: str
    plugin: str
    effort: str
    per_run: float
    trace: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class RunEnd:
    """A job's end: its record, or ``None`` when no session ran; ``error`` when a step failed."""

    record: dict[str, JsonValue] | None
    error: str | None = None


def cases_or_exit(root: Path, *, repos: Sequence[str]) -> tuple[BenchCase, ...]:
    """The hub's cases not excluded, in file order; exit 1 with one line per problem."""
    content = _tasks_content_or_exit(root / TASKS_PATH)
    if content is None:
        return ()
    cases = read_cases(content)
    if isinstance(cases, str):
        fail(f"{TASKS_PATH}: {cases}")
    if (line := unknown_repo_line(cases, repos=repos)) is not None:
        fail(line)
    if problems := case_problems(cases, repos=repos):
        fail(*(f"{TASKS_PATH}: {problem.text}" for problem in problems))
    return tuple(case for case in bench_cases(cases) if not case.excluded)


def _tasks_content_or_exit(path: Path) -> bytes | None:
    """At most ``MAX_CASES_BYTES + 1`` bytes of the cases file; ``None`` when there is none."""
    try:
        descriptor = os.open(path, _OPEN_FLAGS)
    except FileNotFoundError:
        return None
    except OSError as error:
        if os.path.islink(path):
            fail(f"{TASKS_PATH}: {NOT_READ}")
        fail(f"{TASKS_PATH}: {error.strerror or error}")
    with os.fdopen(descriptor, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            fail(f"{TASKS_PATH}: {NOT_READ}")
        try:
            return file.read(MAX_CASES_BYTES + 1)
        except OSError as error:
            fail(f"{TASKS_PATH}: {error.strerror or error}")


@dataclass(frozen=True, kw_only=True, slots=True)
class BenchSteps:
    """The steps in workspace ``workspace`` (the repos' folder), children given ``environ``."""

    workspace: Path
    environ: Mapping[str, str]
    children: ChildGroups = field(default_factory=ChildGroups, repr=False)
    # ``git worktree add``, ``remove`` and ``prune`` on one repo are not safe at the same time:
    # a prune during another job's add deletes the folder the add is filling (AGH-120).
    worktree_admin: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def worktrees(self) -> Path:
        return self.workspace / BENCH_FOLDER / WORKTREES_FOLDER

    @property
    def results(self) -> Path:
        return self.workspace / BENCH_FOLDER / RESULTS_FOLDER

    def run(
        self,
        planned: Sequence[Job],
        *,
        session: SessionPlan,
        parallel: int,
        budget: float,
        clock: Callable[[], datetime.datetime],
    ) -> bool:
        """Run ``planned`` in waves within ``budget``, then print the summary; whether every
        job ran its session and its grade."""
        _make_folder(self.results)
        out = self.results / f"{session.label}.jsonl"
        spent, records, right = 0.0, [], True
        for wave in waves(planned, parallel=parallel):
            line = stop_line(spent=spent, wave=len(wave), per_run=session.per_run, budget=budget)
            if line is not None:
                typer.echo(line)
                break
            with ThreadPoolExecutor(len(wave)) as pool:
                ends = pool.map(lambda job: self._one_run(job, session, clock), wave)
                try:
                    for end in ends:
                        if end.error is not None:
                            right = False
                            typer.echo(shown_text(f"{_PREFIX}: {end.error}"), err=True)
                        if end.record is None:
                            continue
                        records.append(end.record)
                        spent += _spent(end.record)
                        _append_record(out, end.record)
                except BaseException:
                    # Ctrl-C reaches this thread only: the other jobs' children run in their
                    # own sessions, so kill them before the pool waits for its threads.
                    self.children.stop()
                    raise
        typer.echo("\n" + summary(records, spent=spent))
        return right

    def _one_run(
        self, job: Job, session: SessionPlan, clock: Callable[[], datetime.datetime]
    ) -> RunEnd:
        case = job.case
        name = worktree_name(label=session.label, case_id=case.id, arm=job.arm, run=job.run)
        error = None
        try:
            with self.worktree(case, name=name, commit=f"{case.merge}^") as path:
                self._overlay(path)
                agent = self._session(job, path, session)
                try:
                    grade = self.grade(case, path)
                except StepError as failed:
                    error = f"{name}: {failed}"
                    grade = {"pass": False, "error": f"grade: {failed}"}
        except StepError as failed:
            return RunEnd(record=None, error=f"{name}: {failed}")
        ts = clock().strftime(TS_FORMAT)
        record = run_record(label=session.label, job=job, agent=agent, grade=grade, ts=ts)
        return RunEnd(record=record, error=error)

    def _overlay(self, path: Path) -> None:
        """Today's agent config over the old code, so both arms read the same; then unstaged.

        A config file absent from ``origin/main`` is skipped; a checkout or the reset that fails
        is a ``StepError``."""
        worktree = str(path)
        for config in AGENT_CONFIG:
            found = git_argv(worktree, "cat-file", "-e", f"{CONFIG_SOURCE}:{config}")
            if self._run(found, cwd=path, env=self._env, timeout=GIT_TIMEOUT).returncode == 0:
                checkout = git_argv(worktree, "checkout", CONFIG_SOURCE, "--", config)
                self._overlay_step("checkout", checkout, path)
        self._overlay_step("reset", git_argv(worktree, "reset", "-q"), path)

    def _overlay_step(self, step: str, argv: Sequence[str], path: Path) -> None:
        # A session on the old config would be graded as if it read today's: never run it.
        done = self._run(argv, cwd=path, env=self._env, timeout=GIT_TIMEOUT)
        if done.returncode:
            raise StepError(f"overlay {step} failed: {_tail(done.stderr)}")

    def _session(self, job: Job, path: Path, session: SessionPlan) -> dict[str, JsonValue]:
        """One ``claude -p`` session in ``path``; a session past its timeout costs its cap."""
        settings = self.results / settings_name(path.name)
        sandbox = sandbox_settings(
            worktree=str(path), arm=job.arm, plugin=session.plugin, effort=session.effort
        )
        try:
            _write_private(settings, settings_text(sandbox), flags=os.O_TRUNC)
        except OSError as error:
            raise StepError(_open_problem(settings, error)) from None
        argv = agent_argv(
            prompt=job.case.prompt,
            settings_path=str(settings),
            per_run=session.per_run,
            trace=session.trace,
        )
        env = session_env(self._env, case=job.case, arm=job.arm)
        trace = self._trace_path(path.name) if session.trace else None
        started = monotonic()
        try:
            ended = self._start(
                argv,
                cwd=path,
                env=env,
                timeout=AGENT_TIMEOUT,
                own_session=True,
                stdout_path=trace,
            )
        except ChildTimedOutError:
            return timeout_outcome(per_run=session.per_run, secs=int(AGENT_TIMEOUT))
        result = result_of(_text(ended.stdout), trace=session.trace)
        agent = agent_outcome(
            rc=ended.returncode,
            result=result,
            secs=round(monotonic() - started),
            stderr=_text(ended.stderr),
        )
        if ended.returncode and "total_cost_usd" not in result:
            # A failed session that left no cost may have spent up to its cap, as a timeout.
            agent["cost"] = session.per_run
        return agent

    def validate(self, cases: Sequence[BenchCase]) -> bool:
        """Grade each case at its merge's parent and at its merge; whether each grade is right.

        Prints the script's line for each grade, or a ``hub bench: <case> <label>: <why>`` line
        on stderr for a step that failed.
        """
        right = True
        for case in cases:
            for label, commit in validate_commits(case):
                right &= self._validate_at(case, label=label, commit=commit)
        return right

    def _validate_at(self, case: BenchCase, *, label: str, commit: str) -> bool:
        name = validate_worktree_name(case_id=case.id, label=label)
        try:
            with self.worktree(case, name=name, commit=commit) as path:
                grade = self.grade(case, path)
        except StepError as error:
            typer.echo(shown_text(f"{_PREFIX}: {case.id} {label}: {error}"), err=True)
            return False
        typer.echo(validate_line(case_id=case.id, label=label, grade=grade))
        return is_expected(label=label, grade=grade)

    @contextlib.contextmanager
    def worktree(self, case: BenchCase, *, name: str, commit: str) -> Iterator[Path]:
        """The case's repo at ``commit`` in ``<worktrees>/<name>``, set up; removed on exit."""
        path = self.worktrees / name
        repo = self.workspace / case.repo
        if os.path.lexists(path):
            self._remove(repo, path)
        try:
            self.worktrees.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StepError(f"{self.worktrees}: {error.strerror or error}") from None
        try:
            argv = add_worktree_argv(repo=str(repo), worktree=str(path), commit=commit)
            with self.worktree_admin:
                added = self._run(argv, cwd=self.workspace, env=self._env, timeout=GIT_TIMEOUT)
            if added.returncode:
                raise StepError(f"git worktree add failed: {_tail(added.stderr)}")
            if case.setup_cmd:
                setup = self._run(
                    setup_argv(case),
                    cwd=path,
                    env=self._env,
                    timeout=SETUP_TIMEOUT,
                    own_session=True,
                )
                if setup.returncode:
                    raise StepError(f"setup_cmd: {_tail(setup.stderr)}")
            yield path
        finally:
            self._remove(repo, path)

    def grade(self, case: BenchCase, path: Path) -> dict[str, JsonValue]:
        """The merge's hidden tests applied, then the test command on them and on their dirs."""
        applied = self._run(
            apply_tests_argv(worktree=str(path), case=case),
            cwd=path,
            env=self._env,
            timeout=GIT_TIMEOUT,
        )
        if applied.returncode:
            return apply_failed_outcome(_text(applied.stderr))
        env = grader_env(self._env, case=case)
        hidden_argv, related_argv = grader_argvs(case)
        hidden = self._run(hidden_argv, cwd=path, env=env, timeout=GRADER_TIMEOUT, own_session=True)
        related = self._run(
            related_argv, cwd=path, env=env, timeout=GRADER_TIMEOUT, own_session=True
        )
        return grade_outcome(
            hidden_rc=hidden.returncode,
            hidden_stdout=_text(hidden.stdout),
            related_rc=related.returncode,
            related_stdout=_text(related.stdout),
        )

    @property
    def _env(self) -> dict[str, str]:
        return untrusted_env(self.environ)

    def _remove(self, repo: Path, path: Path) -> None:
        """Best effort, as the script: git forgets the worktree, its folder goes, git prunes."""
        remove, prune = remove_worktree_argvs(repo=str(repo), worktree=str(path))
        with self.worktree_admin:
            with contextlib.suppress(StepError):
                self._run(remove, cwd=self.workspace, env=self._env, timeout=GIT_TIMEOUT)
            if os.path.islink(path):
                with contextlib.suppress(OSError):
                    path.unlink()
            else:
                shutil.rmtree(path, ignore_errors=True)
            with contextlib.suppress(StepError):
                self._run(prune, cwd=self.workspace, env=self._env, timeout=GIT_TIMEOUT)

    def _trace_path(self, worktree: str) -> Path:
        """The session's whole stream-json, kept: only its last ``OUTPUT_LIMIT`` bytes are read."""
        traces = self.results / TRACES_FOLDER
        try:
            traces.mkdir(exist_ok=True)
        except OSError as error:
            raise StepError(f"{traces}: {error.strerror or error}") from None
        trace = traces / f"{worktree}.jsonl"
        try:
            # Created owner-only here, so a link at its path is refused before claude starts.
            _write_private(trace, "", flags=os.O_TRUNC)
        except OSError as error:
            raise StepError(_open_problem(trace, error)) from None
        return trace

    def _run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        own_session: bool = False,
    ) -> ChildResult:
        """Run ``argv`` as ``_start`` does; past ``timeout`` it is a ``StepError`` too."""
        try:
            return self._start(argv, cwd=cwd, env=env, timeout=timeout, own_session=own_session)
        except ChildTimedOutError:
            raise StepError(f"{argv[0]} timed out after {timeout:g} s") from None

    def _start(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        own_session: bool,
        stdout_path: Path | None = None,
    ) -> ChildResult:
        """Run ``argv``; a program that cannot start is a ``StepError``.

        In the caller's group, or with ``own_session`` in its own, registered in ``children``
        while it runs (refused once they are stopped), so a timeout or a stop kills the whole
        group. A bare name is looked up on ``env``'s ``PATH``; a name with a ``/`` is run as
        written, from ``cwd``. With ``stdout_path``, stdout is kept there whole. Raises
        ``ChildTimedOutError`` past ``timeout``.
        """
        if own_session and self.children.stopped:
            raise StepError("interrupted")
        name = argv[0]
        program = name if "/" in name else shutil.which(name, path=env.get("PATH", ""))
        if program is None:
            raise StepError(f"{name} is not on PATH")
        if "/" not in name:
            program = os.path.abspath(program)
        groups: list[int] = []

        def started(group: int) -> None:
            groups.append(group)
            self.children.add(group)

        try:
            return run_child(
                [program, *argv[1:]],
                cwd=cwd,
                env=env,
                timeout=timeout,
                own_session=own_session,
                output_limit=OUTPUT_LIMIT,
                stdout_path=stdout_path,
                on_start=started if own_session else None,
            )
        except OSError as error:
            raise StepError(f"{name} could not run: {error.strerror or error}") from None
        finally:
            for group in groups:
                # The leader has ended: what it left in the background (a server, a test
                # worker) ends with it, never outliving the bench.
                _kill_group(group)
                self.children.discard(group)


def _text(output: bytes) -> str:
    return output.decode(errors="replace")


def _tail(output: bytes) -> str:
    return _text(output)[-AGENT_ERROR_CHARS:].strip()


def _make_folder(folder: Path) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        fail(f"{_PREFIX}: {folder}: {error.strerror or error}")


def _append_record(out: Path, record: Mapping[str, JsonValue]) -> None:
    typer.echo(record_line(record))
    try:
        _write_private(out, record_line(record) + "\n", flags=os.O_APPEND)
    except OSError as error:
        fail(f"{_PREFIX}: {_open_problem(out, error)}")


def _write_private(path: Path, text: str, *, flags: int) -> None:
    """Write ``text`` to ``path`` (``O_TRUNC`` or ``O_APPEND``), created owner-only, never
    through a link at ``path``."""
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | flags, PRIVATE_FILE_MODE
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(text)


def _open_problem(path: Path, error: OSError) -> str:
    if error.errno == errno.ELOOP:
        return f"{path}: not opened: links are never followed"
    return f"{path}: {error.strerror or error}"


def _spent(record: Mapping[str, JsonValue]) -> float:
    cost = record.get("cost")
    return float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else 0.0
