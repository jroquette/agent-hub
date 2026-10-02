"""The steps of ``hub bench``: read the cases, add and remove the bench worktrees, grade, run.

The cases come from the hub's ``brain/workflow/bench/tasks.json`` (absent: none, spec Q-6), read
as a regular file only, at most ``MAX_CASES_BYTES + 1`` bytes, then checked in the order of plan
E7: strict JSON, the script's unknown-repo line, each shape problem (E4); each refusal exits 1.
Excluded cases are never run.

Each worktree is a detached checkout of the case's repo under ``<ws>/_bench/wt``, where ``<ws>``
is the folder of the hub's main checkout; a leftover folder there is removed first, and the
worktree is removed when its step ends, whatever ends it (a failure, Ctrl-C). The user's own
checkout is only the repo git adds the worktree to. Every child runs in the caller's process
group without the tracker key or a GitHub token (``untrusted_env``, plan E9); the case's ``env``
reaches the test command only (E17). A step that fails (git, ``setup_cmd``, a test command that
cannot start or runs past its timeout) is that case's failure (``StepError``), never a crash.

A run is the script's: each job's worktree at the merge's parent, today's agent config from
``origin/main`` laid over it, one ``claude -p`` session sandboxed by its settings file, then the
grade. Waves of ``--parallel`` jobs start only while the budget holds (else the script's ``STOP:``
line); each record is printed and appended to ``<ws>/_bench/results/<label>.jsonl`` in job order,
then the summary is printed. A job whose worktree, setup or session cannot start has no record:
its line goes to stderr and the run exits 1 after the summary.
"""

import contextlib
import datetime
import os
import shutil
import stat
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Final

import typer

from agent_hub.cli.child_process import ChildResult, run_child
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
_PREFIX: Final = "hub bench"
# Opened without following a link, and without waiting on a FIFO's writer.
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class StepError(CliError):
    """A step of one case failed; the text says which step and why."""


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
                for end in pool.map(lambda job: self._one_run(job, session, clock), wave):
                    if end.error is not None:
                        right = False
                        typer.echo(shown_text(f"{_PREFIX}: {end.error}"), err=True)
                    if end.record is None:
                        continue
                    records.append(end.record)
                    spent += _spent(end.record)
                    _append_record(out, end.record)
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
        """Today's agent config over the old code, so both arms read the same; then unstaged."""
        worktree = str(path)
        for config in AGENT_CONFIG:
            found = git_argv(worktree, "cat-file", "-e", f"{CONFIG_SOURCE}:{config}")
            if self._run(found, cwd=path, env=self._env, timeout=GIT_TIMEOUT).returncode == 0:
                checkout = git_argv(worktree, "checkout", CONFIG_SOURCE, "--", config)
                self._run(checkout, cwd=path, env=self._env, timeout=GIT_TIMEOUT)
        self._run(git_argv(worktree, "reset", "-q"), cwd=path, env=self._env, timeout=GIT_TIMEOUT)

    def _session(self, job: Job, path: Path, session: SessionPlan) -> dict[str, JsonValue]:
        """One ``claude -p`` session in ``path``; a session past its timeout costs its cap."""
        settings = self.results / settings_name(path.name)
        sandbox = sandbox_settings(
            worktree=str(path), arm=job.arm, plugin=session.plugin, effort=session.effort
        )
        try:
            settings.write_text(settings_text(sandbox), encoding="utf-8")
        except OSError as error:
            raise StepError(f"{settings}: {error.strerror or error}") from None
        argv = agent_argv(
            prompt=job.case.prompt,
            settings_path=str(settings),
            per_run=session.per_run,
            trace=session.trace,
        )
        env = session_env(self._env, case=job.case, arm=job.arm)
        started = monotonic()
        try:
            ended = self._start(argv, cwd=path, env=env, timeout=AGENT_TIMEOUT)
        except ChildTimedOutError:
            return timeout_outcome(per_run=session.per_run, secs=int(AGENT_TIMEOUT))
        return agent_outcome(
            rc=ended.returncode,
            result=result_of(_text(ended.stdout), trace=session.trace),
            secs=round(monotonic() - started),
            stderr=_text(ended.stderr),
        )

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
            added = self._run(argv, cwd=self.workspace, env=self._env, timeout=GIT_TIMEOUT)
            if added.returncode:
                raise StepError(f"git worktree add failed: {_tail(added.stderr)}")
            if case.setup_cmd:
                setup = self._run(setup_argv(case), cwd=path, env=self._env, timeout=SETUP_TIMEOUT)
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
        hidden = self._run(hidden_argv, cwd=path, env=env, timeout=GRADER_TIMEOUT)
        related = self._run(related_argv, cwd=path, env=env, timeout=GRADER_TIMEOUT)
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
        with contextlib.suppress(StepError):
            self._run(remove, cwd=self.workspace, env=self._env, timeout=GIT_TIMEOUT)
        if os.path.islink(path):
            with contextlib.suppress(OSError):
                path.unlink()
        else:
            shutil.rmtree(path, ignore_errors=True)
        with contextlib.suppress(StepError):
            self._run(prune, cwd=self.workspace, env=self._env, timeout=GIT_TIMEOUT)

    def _run(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float
    ) -> ChildResult:
        """Run ``argv`` in the caller's group; a program that cannot start or runs past
        ``timeout`` is a ``StepError``."""
        try:
            return self._start(argv, cwd=cwd, env=env, timeout=timeout)
        except ChildTimedOutError:
            raise StepError(f"{argv[0]} timed out after {timeout:g} s") from None

    def _start(
        self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float
    ) -> ChildResult:
        """Run ``argv`` in the caller's group; a program that cannot start is a ``StepError``.

        A bare name is looked up on ``env``'s ``PATH``; a name with a ``/`` is run as written,
        from ``cwd``. Raises ``ChildTimedOutError`` past ``timeout``.
        """
        name = argv[0]
        program = name if "/" in name else shutil.which(name, path=env.get("PATH", ""))
        if program is None:
            raise StepError(f"{name} is not on PATH")
        if "/" not in name:
            program = os.path.abspath(program)
        try:
            return run_child(
                [program, *argv[1:]],
                cwd=cwd,
                env=env,
                timeout=timeout,
                own_session=False,
                output_limit=OUTPUT_LIMIT,
            )
        except OSError as error:
            raise StepError(f"{name} could not run: {error.strerror or error}") from None


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
        with out.open("a", encoding="utf-8") as file:
            file.write(record_line(record) + "\n")
    except OSError as error:
        fail(f"{_PREFIX}: {out}: {error.strerror or error}")


def _spent(record: Mapping[str, JsonValue]) -> float:
    cost = record.get("cost")
    return float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else 0.0
