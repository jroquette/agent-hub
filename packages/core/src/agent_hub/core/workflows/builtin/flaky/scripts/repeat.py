# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run one pytest test many times, alone, in its file's order, shuffled and in parallel; print
the counts as one JSON object.

``repeat.py --repo <dir> --test <node id> --runs <1-200> --config <json> [--run-timeout <seconds>]
[--budget <seconds>]``, run in the hub: ``--config`` is ``hub step config``'s output, ``<dir>`` one
of its repos, checked out beside the hub, and the node id is relative to that repo's root
(``tests/test_x.py::test_y[case]``). The test runs in a throwaway detached ``git worktree`` of the
repo at ``origin/<default branch>`` (as last fetched: fetch first), made in a new temporary folder
and removed afterwards, so the repo's checkout is left as it was. The runner comes from the
worktree: ``uv run --locked [--all-packages] python`` when it holds ``uv.lock``, else
``.venv/bin/python``, else ``python3``; tests run as ``<runner> -m pytest``.

Each of ``--runs`` rounds runs every available mode once: ``alone`` (the node id), ``suite`` (its
file, default order), ``shuffled`` (its file under pytest-randomly or pytest-random-order, seed
``1000 + round``) and ``parallel`` (its folder under pytest-xdist ``-n auto``). A mode whose plugin
the runner's Python lacks is ``unavailable`` and never run. Each run's result is the test's own
``-rA`` summary line (``XFAIL`` and ``XPASS``: ``skipped``); with no line, ``alone`` reads the exit
code (a skip on its first run exits 2: the test is skipped here), the others count ``missing``.
A run still going after ``--run-timeout`` (default 600 s) is killed with its process group; once
``--budget`` (default 5 h 30 min, under the node's timeout) is spent, the rest are ``not_run``.

Output: ``{"test", "repo", "repo_path", "sha", "runner", "runs", "budget_spent", "reproduced",
"modes": [{"mode", "status", "note", "passed", "failed", "errors", "timed_out", "missing",
"skipped", "not_run", "tails"}]}``: ``reproduced`` is true when the test failed or erred in a run,
or timed out alone. In the file and folder modes a timeout or a missing line is the whole run's,
so it is inconclusive: counted, said in the mode's note, never a reproduction. ``tails`` holds at
most 3 output tails of failing, erring, timed-out or missing runs, each at most 500 characters.
Bad input (a test id pytest could misread, one that names no file, collects other than one test
or is skipped here) exits 2; a base that cannot be checked out or a runner that cannot start
exits 1. Both say why on stderr.

Limits: a run killed by the engine (a node timeout, a cancel) cannot remove its worktree: its
temporary folder and entry stay until removed by hand or by the temporary folder's cleanup, and
the next run's ``git worktree prune`` then drops the entry. Each pytest run starts a session of
its own (so its whole process group can be killed at ``--run-timeout``), which puts it outside the
group the engine kills: a run going when this script is killed goes on until it ends by itself.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import contextlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO

USAGE = (
    "usage: repeat.py --repo <dir> --test <node id> --runs <1-200> --config <json>"
    " [--run-timeout <seconds>] [--budget <seconds>]"
)
NAMES = frozenset({"--repo", "--test", "--runs", "--config", "--run-timeout", "--budget"})
REQUIRED = frozenset({"--repo", "--test", "--runs", "--config"})
MAX_RUNS = 200
RUN_TIMEOUT = 600.0
SETUP_TIMEOUT = 1200.0
BUDGET = 5 * 3600 + 30 * 60.0
MAX_CONFIG_BYTES = 64 * 1024
MAX_TEST_CHARS = 512
MAX_PYPROJECT_CHARS = 1024 * 1024
LINE_BYTES = 64 * 1024
TAIL_BYTES = 4096
TAIL_CHARS = 500
MAX_TAILS = 3
NOTE_CHARS = 200
SEED_BASE = 1000
MODES = ("alone", "suite", "shuffled", "parallel")
COUNTS = ("passed", "failed", "errors", "timed_out", "missing", "skipped", "not_run")
# The results that are the test's own: in the file and folder modes a timeout or a lost line
# belongs to the whole run, so it is inconclusive, never a reproduction.
REPRODUCED = {"alone": ("failed", "errors", "timed_out")}
FILE_REPRODUCED = ("failed", "errors")
INCONCLUSIVE = ("timed_out", "missing")
PLUGINS = ("xdist", "pytest_randomly", "random_order")
PYTEST = ("-m", "pytest", "-p", "no:cacheprovider", "--color=no")
COMMON = (*PYTEST, "-rA", "-q")
# One fixed program, no input in it: which of the modes' plugins the runner's Python has.
DETECT = (
    "import importlib.util as u, json; print(json.dumps({n: u.find_spec(n) is not None"
    " for n in ('xdist', 'pytest_randomly', 'random_order')}))"
)
# ``<path>.py::<name>[::<name>...][<params>]``; no leading ``-`` (an option) or ``@`` (pytest 8.2
# and newer reads ``@file`` as a file of arguments).
NODE_ID = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.py(::[A-Za-z_][A-Za-z0-9_]*)+(\[[\x20-\x7e]*\])?"
)
BRANCH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
# Every control character but the newline and the tab, for an output's tail.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
LINE_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# The test's own ``-rA`` lines, the first found winning; an expected failure (``XFAIL``) or an
# unexpected pass (``XPASS``) is a skip, never a reproduction. ``SKIPPED`` lines name no test.
SUMMARY = (
    ("ERROR", "errors"),
    ("FAILED", "failed"),
    ("PASSED", "passed"),
    ("XFAIL", "skipped"),
    ("XPASS", "skipped"),
)
SKIPPED_LINE = "SKIPPED ["

CHECKS: tuple[tuple[Callable[[str], bool], str], ...] = (
    (lambda test: len(test) > MAX_TEST_CHARS, f"is over {MAX_TEST_CHARS} characters"),
    (lambda test: test[:1] in {"-", "@"}, "starts with - or @, which pytest reads as no test"),
    (lambda test: bool(LINE_CONTROL.search(test)), "holds a control character"),
    (lambda test: test.startswith("/"), "is absolute"),
    (lambda test: ".." in PurePosixPath(file_of(test)).parts, "holds a .. segment"),
    (lambda test: "::" not in test, "has no ::"),
    (
        lambda test: not NODE_ID.fullmatch(test),
        "is not a pytest node id (<path>.py::<name>[::<name>][[<params>]])",
    ),
)


class BadInputError(Exception):
    """The input is not what this script runs."""


class CannotRunError(Exception):
    """The base cannot be checked out, or the runner cannot start in the worktree."""


@dataclass(frozen=True)
class Request:
    repo: str
    test: str
    runs: int
    run_timeout: float
    budget: float


@dataclass
class Mode:
    """One mode's counts, its failing runs' tails and the note that says how it ran."""

    name: str
    note: str
    status: str = "ran"
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNTS, 0))
    tails: list[str] = field(default_factory=list)

    def record(self, result: str, tail: str, label: str) -> None:
        self.counts[result] += 1
        if result not in {"passed", "skipped"} and len(self.tails) < MAX_TAILS:
            head = f"{label}: "
            self.tails.append(head + tail[-(TAIL_CHARS - len(head)) :])

    def reproduced(self) -> bool:
        return any(self.counts[key] for key in REPRODUCED.get(self.name, FILE_REPRODUCED))

    def output(self) -> dict[str, object]:
        found: dict[str, object] = {"mode": self.name, "status": self.status}
        note = self.note
        if self.name != "alone" and any(self.counts[key] for key in INCONCLUSIVE):
            what = "folder" if self.name == "parallel" else "file"
            suffix = f"; the {what} run timed out or printed no line for the test: inconclusive"
            note = note[: NOTE_CHARS - len(suffix)] + suffix
        found["note"] = note[:NOTE_CHARS]
        return {**found, **self.counts, "tails": self.tails}


def file_of(test: str) -> str:
    return test.split("::", 1)[0]


def folder_of(test: str) -> str:
    return str(PurePosixPath(file_of(test)).parent)


def check_test_id(test: str) -> None:
    for broken, reason in CHECKS:
        if broken(test):
            raise BadInputError(f"the test id {test[:80]!r} {reason}")


def options(argv: list[str]) -> dict[str, str]:
    given = dict(zip(argv[::2], argv[1::2], strict=False))
    if len(argv) % 2 or not set(given) <= NAMES or not set(given) >= REQUIRED:
        raise BadInputError(USAGE)
    return given


def seconds(given: dict[str, str], name: str, default: float) -> float:
    try:
        value = float(given.get(name, default))
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value < 0 or (value == 0 and name == "--run-timeout"):
        raise BadInputError(f"{name} is not a number of seconds: {given.get(name, '')[:20]!r}")
    return value


def request(given: dict[str, str]) -> Request:
    runs = given["--runs"]
    if not (runs.isascii() and runs.isdecimal() and 1 <= int(runs) <= MAX_RUNS):
        raise BadInputError(f"--runs is not a count from 1 to {MAX_RUNS}: {runs[:20]!r}")
    check_test_id(given["--test"])
    return Request(
        repo=given["--repo"],
        test=given["--test"],
        runs=int(runs),
        run_timeout=seconds(given, "--run-timeout", RUN_TIMEOUT),
        budget=seconds(given, "--budget", BUDGET),
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - git with fixed arguments
        ["git", "-C", str(repo), *args],  # noqa: S607 - git from PATH
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def read_config(text: str) -> dict[str, object]:
    if len(text.encode(errors="surrogatepass")) > MAX_CONFIG_BYTES:
        raise BadInputError("--config is over 64 KiB")
    try:
        config = json.loads(text)
    except ValueError:
        raise BadInputError("--config is not JSON") from None
    if not isinstance(config, dict) or not isinstance(config.get("repos"), list):
        raise BadInputError("--config has no repos list")
    return config


def checkout(name: str, text: str) -> tuple[Path, str]:
    """``name``'s checkout beside the hub and its default branch, once the config lists it."""
    config = read_config(text)
    repos = config["repos"]
    found = [
        item
        for item in (repos if isinstance(repos, list) else [])
        if isinstance(item, dict) and item.get("dir") == name
    ]
    if not found:
        raise BadInputError(f"{name!r} is not a repo of the config")
    branch = found[0].get("default_branch") or config.get("default_branch") or "main"
    if not (isinstance(branch, str) and BRANCH.fullmatch(branch) and ".." not in branch):
        raise BadInputError(f"the default branch of {name!r} is not a branch name")
    path = (Path.cwd().parent / name).resolve()
    if not path.is_dir() or git(path, "rev-parse", "--git-dir").returncode != 0:
        raise BadInputError(f"the repo {name!r} is not a git checkout at {path}")
    return path, branch


def base(repo: Path, branch: str) -> str:
    found = git(repo, "rev-parse", "--verify", "--quiet", f"origin/{branch}^{{commit}}")
    if found.returncode != 0:
        raise CannotRunError(f"cannot check out origin/{branch}: no such commit (fetch first)")
    return found.stdout.decode(errors="replace").strip()


@contextlib.contextmanager
def worktree(repo: Path, sha: str) -> Iterator[Path]:
    """A detached worktree of ``repo`` at ``sha`` in a new temporary folder, removed afterwards."""
    # A run killed before its cleanup (a node timeout) leaves its folder and entry behind; prune
    # drops an entry once its folder is gone. Other flaky-* folders are never removed here: a
    # concurrent run on the same repo may be using one.
    git(repo, "worktree", "prune")
    folder = Path(tempfile.mkdtemp(prefix="flaky-"))
    path = folder / "checkout"
    try:
        made = git(repo, "worktree", "add", "--detach", "--quiet", str(path), sha)
        if made.returncode != 0:
            detail = made.stderr.decode(errors="replace").strip()[-300:]
            raise CannotRunError(f"cannot check out {sha[:12]}: {detail}")
        yield path
    finally:
        git(repo, "worktree", "remove", "--force", str(path))
        shutil.rmtree(folder, ignore_errors=True)
        git(repo, "worktree", "prune")


def check_file(path: Path, test: str) -> None:
    root = path.resolve()
    target = (root / file_of(test)).resolve()
    if not (target.is_relative_to(root) and target.is_file()):
        raise BadInputError(f"{file_of(test)[:80]!r} names no file of the repo at its base")


def runner(path: Path) -> list[str]:
    """The Python the worktree's tests run on, as a command prefix."""
    if (path / "uv.lock").is_file():
        found = ["uv", "run", "--locked"]
        if workspace_root(path / "pyproject.toml"):
            found.append("--all-packages")
        return [*found, "python"]
    venv = path / ".venv" / "bin" / "python"
    return [str(venv)] if venv.is_file() else ["python3"]


def workspace_root(pyproject: Path) -> bool:
    """Whether ``pyproject`` holds a ``[tool.uv.workspace]`` line (a text match: no tomllib)."""
    try:
        with pyproject.open(encoding="utf-8", errors="replace") as file:
            text = file.read(MAX_PYPROJECT_CHARS)
    except OSError:
        return False
    return any(line.strip() == "[tool.uv.workspace]" for line in text.splitlines())


def clean_env() -> dict[str, str]:
    """This environment without the script's own virtualenv, which ``uv run`` sets."""
    env = dict(os.environ)
    venv = env.pop("VIRTUAL_ENV", "")
    if venv:
        own = str(Path(venv) / "bin")
        paths = env.get("PATH", "").split(os.pathsep)
        env["PATH"] = os.pathsep.join(item for item in paths if item != own)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def execute(argv: list[str], *, cwd: Path, timeout: float, output: IO[bytes]) -> int | None:
    """``argv``'s exit code, its output in ``output``; ``None`` once killed at ``timeout``."""
    process = subprocess.Popen(  # noqa: S603 - argv list, no shell: the runner and pytest
        argv,
        cwd=cwd,
        env=clean_env(),
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    with contextlib.suppress(ProcessLookupError, PermissionError):
        # The whole group, so nothing the run started outlives it.
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    return None if timed_out else process.returncode


def tail_of(output: IO[bytes]) -> str:
    size = output.seek(0, 2)
    output.seek(max(0, size - TAIL_BYTES))
    return CONTROL.sub("", output.read().decode(errors="replace"))[-TAIL_CHARS:]


def lines_of(output: IO[bytes]) -> Iterator[str]:
    """``output``'s lines, each read at most ``LINE_BYTES`` at a time."""
    output.seek(0)
    for raw in iter(lambda: output.readline(LINE_BYTES), b""):
        yield raw.decode(errors="replace").rstrip("\r\n")


def summary_result(output: IO[bytes], test: str) -> str:
    """The test's result from its own ``-rA`` summary lines: an error wins over a failure."""
    found = set()
    for text in lines_of(output):
        for status, _ in SUMMARY:
            if text == f"{status} {test}" or text.startswith(f"{status} {test} - "):
                found.add(status)
    for status, result in SUMMARY:
        if status in found:
            return result
    return "missing"


def alone_result(output: IO[bytes], code: int, test: str) -> str:
    """The alone run's result: its summary line, else ``skip`` when pytest skipped it (exit 0
    and a ``SKIPPED`` line), else the exit code's."""
    found = summary_result(output, test)
    if found != "missing":
        return found
    if code == 0 and any(text.startswith(SKIPPED_LINE) for text in lines_of(output)):
        return "skip"
    return {0: "passed", 1: "failed"}.get(code, "errors")


def run_once(argv: list[str], *, cwd: Path, timeout: float, test: str) -> tuple[str, str]:
    """One run's result for ``test`` and its output's tail; an argv ending in ``test`` (the
    alone mode) falls back on the exit code."""
    with tempfile.TemporaryFile() as output:
        code = execute(argv, cwd=cwd, timeout=timeout, output=output)
        if code is None:
            result = "timed_out"
        elif argv[-1] == test:
            result = alone_result(output, code, test)
        else:
            result = summary_result(output, test)
        return result, tail_of(output)


def detect(python: list[str], path: Path) -> dict[str, bool]:
    """Which of the modes' plugins the runner's Python has."""
    with tempfile.TemporaryFile() as output:
        try:
            code = execute([*python, "-c", DETECT], cwd=path, timeout=SETUP_TIMEOUT, output=output)
        except OSError as error:
            raise CannotRunError(f"cannot run {' '.join(python)}: {error.strerror}") from None
        last = [line for line in lines_of(output) if line.strip()][-1:]
    try:
        found = json.loads(last[0]) if code == 0 and last else None
    except ValueError:
        found = None
    if not isinstance(found, dict):
        detail = last[0][:300] if last else f"exit {code}"
        raise CannotRunError(f"cannot run {' '.join(python)} in the worktree: {detail}")
    return {name: found.get(name) is True for name in PLUGINS}


def no_randomly(plugins: dict[str, bool]) -> list[str]:
    return ["-p", "no:randomly"] if plugins.get("pytest_randomly") else []


def count_collected(output: IO[bytes]) -> int:
    """The node ids ``--collect-only -q`` printed: the first block of lines holding ``::``."""
    count = 0
    for text in lines_of(output):
        if count and not text.strip():
            break
        if count or "::" in text:
            count += 1
    return count


def check_collects(python: list[str], path: Path, *, test: str, plugins: dict[str, bool]) -> None:
    argv = [*python, *PYTEST, "--collect-only", "-q", *no_randomly(plugins), test]
    with tempfile.TemporaryFile() as output:
        code = execute(argv, cwd=path, timeout=SETUP_TIMEOUT, output=output)
        collected = count_collected(output) if code == 0 else 0
        last = [line for line in lines_of(output) if line.strip()][-1:]
    if collected != 1:
        detail = last[0][:300] if last else f"exit {code}"
        raise BadInputError(f"{test[:80]!r} collects {collected} tests, not 1: {detail}")


def mode_argv(name: str, plugins: dict[str, bool], *, test: str, seed: int) -> list[str]:
    """The pytest arguments of one run of mode ``name``, after the common ones."""
    if name == "alone":
        return [*no_randomly(plugins), test]
    if name == "suite":
        return [*no_randomly(plugins), file_of(test)]
    if name == "shuffled":
        if plugins.get("pytest_randomly"):
            return ["-p", "randomly", f"--randomly-seed={seed}", file_of(test)]
        return [f"--random-order-seed={seed}", file_of(test)]
    return [*no_randomly(plugins), "-n", "auto", folder_of(test)]


def plan(plugins: dict[str, bool], python: list[str], req: Request) -> list[Mode]:
    seeds = f"seeds {SEED_BASE + 1}-{SEED_BASE + req.runs}"
    shuffler = "pytest-randomly" if plugins["pytest_randomly"] else "pytest-random-order"
    modes = [
        Mode("alone", f"the test alone, through {' '.join(python)}"),
        Mode("suite", f"{file_of(req.test)} in its default order"),
        Mode("shuffled", f"{file_of(req.test)} shuffled by {shuffler}, {seeds}"),
        Mode("parallel", f"the folder {folder_of(req.test)} under pytest-xdist -n auto"),
    ]
    if not (plugins["pytest_randomly"] or plugins["random_order"]):
        modes[2].status = "unavailable"
        modes[2].note = "skipped: neither pytest-randomly nor pytest-random-order is installed"
    if not plugins["xdist"]:
        modes[3].status = "unavailable"
        modes[3].note = "skipped: pytest-xdist is not installed"
    return modes


def run_all(
    modes: list[Mode], *, setup: tuple[list[str], Path, dict[str, bool]], req: Request, start: float
) -> bool:
    """Round after round, each available mode once; whether the budget ran out."""
    python, path, plugins = setup
    spent = False
    for index in range(req.runs):
        seed = SEED_BASE + index + 1
        for mode in (item for item in modes if item.status == "ran"):
            if time.monotonic() - start >= req.budget:
                mode.counts["not_run"] += 1
                spent = True
                continue
            argv = [*python, *COMMON, *mode_argv(mode.name, plugins, test=req.test, seed=seed)]
            result, tail = run_once(argv, cwd=path, timeout=req.run_timeout, test=req.test)
            if result == "skip":
                result = skipped_here(tail, test=req.test, first=index == 0)
            label = (
                f"run {index + 1}, seed {seed}" if mode.name == "shuffled" else f"run {index + 1}"
            )
            mode.record(result, tail, label)
    return spent


def skipped_here(tail: str, *, test: str, first: bool) -> str:
    """``skipped`` for a later skip; a skip on the first alone run stops the run."""
    if not first:
        return "skipped"
    reason = [text for text in tail.splitlines() if text.startswith(SKIPPED_LINE)][-1:]
    detail = f": {reason[0][:200]}" if reason else ""
    raise BadInputError(f"{test[:80]!r}: the test is skipped here{detail}")


def measure(req: Request, *, repo: Path, sha: str, start: float) -> dict[str, object]:
    with worktree(repo, sha) as path:
        check_file(path, req.test)
        python = runner(path)
        plugins = detect(python, path)
        check_collects(python, path, test=req.test, plugins=plugins)
        modes = plan(plugins, python, req)
        spent = run_all(modes, setup=(python, path, plugins), req=req, start=start)
    return {
        "test": req.test,
        "repo": req.repo,
        "repo_path": str(repo),
        "sha": sha,
        "runner": python,
        "runs": req.runs,
        "budget_spent": spent,
        "reproduced": any(mode.reproduced() for mode in modes),
        "modes": [mode.output() for mode in modes],
    }


def main(argv: list[str]) -> int:
    start = time.monotonic()
    try:
        given = options(argv)
        req = request(given)
        repo, branch = checkout(req.repo, given["--config"])
        found = measure(req, repo=repo, sha=base(repo, branch), start=start)
    except BadInputError as error:
        print(f"repeat.py: {error}", file=sys.stderr)
        return 2
    except CannotRunError as error:
        print(f"repeat.py: {error}", file=sys.stderr)
        return 1
    print(json.dumps(found, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
