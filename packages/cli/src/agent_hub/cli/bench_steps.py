"""The steps of ``hub bench``: read the cases, add and remove the bench worktrees, grade.

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
"""

import contextlib
import os
import shutil
import stat
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
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
from agent_hub.core.bench.bench_session import (
    AGENT_ERROR_CHARS,
    add_worktree_argv,
    apply_failed_outcome,
    apply_tests_argv,
    grade_outcome,
    grader_argvs,
    grader_env,
    remove_worktree_argvs,
    setup_argv,
    validate_commits,
    validate_worktree_name,
)
from agent_hub.core.bench.bench_summary import is_expected, validate_line
from agent_hub.core.doctor.bench_rule import NOT_READ
from agent_hub.core.json_form import JsonValue

BENCH_FOLDER: Final = "_bench"
WORKTREES_FOLDER: Final = "wt"
# The script's timeouts, in seconds.
GIT_TIMEOUT: Final = 1_800.0
SETUP_TIMEOUT: Final = 600.0
GRADER_TIMEOUT: Final = 1_800.0
# The bytes kept of each stream of a child: a grade reads the last line only.
OUTPUT_LIMIT: Final = 1 << 20
_PREFIX: Final = "hub bench"
# Opened without following a link, and without waiting on a FIFO's writer.
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class StepError(CliError):
    """A step of one case failed; the text says which step and why."""


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
        """Run ``argv`` in the caller's group; a program that cannot start is a ``StepError``.

        A bare name is looked up on ``env``'s ``PATH``; a name with a ``/`` is run as written,
        from ``cwd``.
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
        except ChildTimedOutError:
            raise StepError(f"{name} timed out after {timeout:g} s") from None
        except OSError as error:
            raise StepError(f"{name} could not run: {error.strerror or error}") from None


def _text(output: bytes) -> str:
    return output.decode(errors="replace")


def _tail(output: bytes) -> str:
    return _text(output)[-AGENT_ERROR_CHARS:].strip()
