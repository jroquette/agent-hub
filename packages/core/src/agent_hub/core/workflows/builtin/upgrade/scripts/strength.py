# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Report the files changed after the bump and run test strength on their changed lines.

``strength.py --base <bump commit> --budget <seconds>``, run in the repo's worktree; the
``/test-strength`` skill's steps 1-2 (scope the diff, find and run the repo's mutation tool). It
reads ``git diff <base>..HEAD``: ``touched`` counts every file changed (tests included, at most
``MAX_FILES`` listed in ``files``) and ``lockfiles_edited`` lists the manifests and lockfiles
among them, which only the tooling may change. The mutation run covers the added lines of
non-test files (at most ``MAX_RANGES`` ranges): Stryker, when the nearest ``package.json`` of a
changed JavaScript or TypeScript file lists ``@stryker-mutator/core``, runs as
``npx --no-install stryker run --mutate <file>:<a>-<b>,...`` in that folder, in its own process
group killed past the budget, and its JSON report (at most 8 MiB, removed when the run made it)
gives the mutants on those lines. A Python tool (mutmut, cosmic-ray) needs a per-repo setup, so
it is named and not run; with no tool, none is run. A tool not run, past its budget or without a
readable report is ``ran: false`` with the reason, never a clean result. The output is
``{"touched", "files", "lockfiles_edited", "ran", "tool", "reason", "mutants", "killed",
"inconclusive", "survived", "more_survived"}`` (at most ``MAX_SURVIVED`` survivors listed).
A bad argument exits 2; a tool that leaves a tracked file changed exits 1.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

COMMIT = re.compile(r"[0-9a-f]{7,40}")
# A hunk header; "@{2}", as the hub's renderer reads two at signs as its own marker.
HUNK = re.compile(r"@{2} -[0-9,]+ \+([0-9]+)(?:,([0-9]+))? @{2}")
TEST_NAME = re.compile(r"(test_.*\.py|.*_test\.py|.*\.(test|spec)\.[A-Za-z0-9]+)")
TEST_DIRS = frozenset({"test", "tests", "e2e", "__tests__"})
JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
MANIFESTS_AND_LOCKFILES = frozenset(
    {"pyproject.toml", "uv.lock", "package.json", "package-lock.json"}
)
PYTHON_TOOLS = ("mutmut", "cosmic-ray", "cosmic_ray")
STRYKER = "@stryker-mutator/core"
REPORT = Path("reports/mutation/mutation.json")
KILLED = frozenset({"Killed", "Timeout"})
SURVIVED = frozenset({"Survived", "NoCoverage"})
NOT_COUNTED = frozenset({"Ignored", "Pending"})
MAX_FILES = 200
MAX_RANGES = 500
MAX_SURVIVED = 50
MAX_LOCKFILES = 50
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BUDGET = 3600

Ranges = dict[str, list[tuple[int, int]]]


class StrengthError(Exception):
    """A failure that exits 1."""


def git(*args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git with fixed arguments
        ["git", *args],  # noqa: S607 - git from PATH, as the worktree's
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        timeout=120,
    )
    if done.returncode != 0:
        raise StrengthError(f"git {args[0]} failed: {done.stderr.strip()[-500:]}")
    return done.stdout


def is_test(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(TEST_DIRS.intersection(parts[:-1])) or bool(TEST_NAME.fullmatch(parts[-1]))


def lockfile_or_manifest(path: str) -> bool:
    """The files only the tooling may change (the set ``bump.py`` accepts)."""
    return PurePosixPath(path).name in MANIFESTS_AND_LOCKFILES


def touched(base: str) -> list[str]:
    names = git("diff", "--name-only", "-z", "--no-renames", f"{base}..HEAD")
    return sorted(name for name in names.split("\0") if name)


def changed(base: str) -> Ranges:
    """The added line ranges of each changed non-test source file."""
    ranges: Ranges = {}
    current = ""
    for line in git("diff", "-U0", "--no-renames", "--no-color", f"{base}..HEAD").splitlines():
        if line.startswith("+++ "):
            name = line[4:].removeprefix("b/")
            keep = line != "+++ /dev/null" and not is_test(name) and not lockfile_or_manifest(name)
            current = name if keep else ""
            continue
        hunk = HUNK.match(line) if current else None
        count = int(hunk.group(2) or "1") if hunk else 0
        if hunk and count and sum(len(v) for v in ranges.values()) < MAX_RANGES:
            start = int(hunk.group(1))
            ranges.setdefault(current, []).append((start, start + count - 1))
    return ranges


def read_bounded(path: Path, limit: int) -> str | None:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        return None
    return data.decode("utf-8", errors="replace") if len(data) <= limit else None


def stryker_folder(path: str) -> str | None:
    """The nearest folder above ``path`` whose ``package.json`` lists Stryker."""
    for folder in PurePosixPath(path).parents:
        text = read_bounded(Path(folder) / "package.json", MAX_MANIFEST_BYTES)
        if text is None:
            continue
        try:
            manifest = json.loads(text)
        except ValueError:
            return None
        sections = [manifest.get(key) for key in ("devDependencies", "dependencies")]
        listed = any(isinstance(deps, dict) and STRYKER in deps for deps in sections)
        return str(folder) if listed else None
    return None


def python_tool() -> str:
    text = " ".join(
        read_bounded(Path(name), 16 * MAX_MANIFEST_BYTES) or ""
        for name in ("pyproject.toml", "uv.lock")
    )
    for tool in PYTHON_TOOLS:
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(tool)}(?![A-Za-z0-9_-])", text):
            return tool.replace("_", "-")
    return ""


def empty(files: list[str]) -> dict[str, object]:
    return {
        "touched": len(files),
        "files": files[:MAX_FILES],
        "lockfiles_edited": [path for path in files if lockfile_or_manifest(path)][:MAX_LOCKFILES],
        "lockfile_edit": any(lockfile_or_manifest(path) for path in files),
        "ran": False,
        "tool": "",
        "reason": "",
        "mutants": 0,
        "killed": 0,
        "inconclusive": 0,
        "survived": [],
        "more_survived": 0,
    }


def tracked_changes() -> set[str]:
    status = git("status", "--porcelain", "-z", "--untracked-files=no")
    return {entry[3:] for entry in status.split("\0") if len(entry) > 3}


class BudgetSpentError(Exception):
    """Stryker ran past the budget left."""


def run_stryker(folder: str, ranges: Ranges, budget: float) -> int | None:
    """Run Stryker on ``ranges`` (all inside ``folder``); its exit code, None when it cannot run.

    A report left by an earlier run is removed first, so only this run's report is read.
    """
    (Path(folder) / REPORT).unlink(missing_ok=True)
    mutate = ",".join(
        f"{PurePosixPath(path).relative_to(folder)}:{a}-{b}"
        for path, spans in sorted(ranges.items())
        for a, b in spans
    )
    argv = ["npx", "--no-install", "stryker", "run", "--mutate", mutate]
    argv += ["--coverageAnalysis", "perTest", "--reporters", "json"]
    try:
        child = subprocess.Popen(  # noqa: S603 - the repo's own Stryker, fixed arguments
            argv,
            cwd=folder,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None
    try:
        return child.wait(timeout=budget)
    except subprocess.TimeoutExpired as error:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        raise BudgetSpentError from error


class Tally:
    """The mutants counted over every folder measured."""

    def __init__(self) -> None:
        self.mutants = self.killed = self.inconclusive = 0
        self.survived: list[dict[str, object]] = []
        self.measured = 0

    def fill(self, result: dict[str, object]) -> None:
        result.update(
            ran=self.measured > 0,
            mutants=self.mutants,
            killed=self.killed,
            inconclusive=self.inconclusive,
            survived=self.survived[:MAX_SURVIVED],
            more_survived=max(0, len(self.survived) - MAX_SURVIVED),
        )


def read_report(folder: str, ranges: Ranges, tally: Tally) -> bool:
    """Add the report's mutants on the changed lines to ``tally``; False when it is unreadable."""
    text = read_bounded(Path(folder) / REPORT, MAX_REPORT_BYTES)
    try:
        report = json.loads(text) if text is not None else None
    except ValueError:
        report = None
    reported = report.get("files") if isinstance(report, dict) else None
    if not isinstance(reported, dict):
        return False
    for name, entry in sorted(reported.items()):
        path = str(PurePosixPath(folder) / str(name))
        mutants = entry.get("mutants") if isinstance(entry, dict) else None
        for mutant in mutants if isinstance(mutants, list) else []:
            line = _line(mutant)
            status = mutant.get("status") if isinstance(mutant, dict) else None
            spans = ranges.get(path, [])
            if line is None or status in NOT_COUNTED or not any(a <= line <= b for a, b in spans):
                continue
            tally.mutants += 1
            if status in KILLED:
                tally.killed += 1
            elif status in SURVIVED:
                tally.survived.append(_survivor(path, line, mutant))
            else:
                tally.inconclusive += 1
    return True


def _line(mutant: object) -> int | None:
    location = mutant.get("location") if isinstance(mutant, dict) else None
    start = location.get("start") if isinstance(location, dict) else None
    line = start.get("line") if isinstance(start, dict) else None
    return line if isinstance(line, int) else None


def _survivor(path: str, line: int, mutant: dict[str, object]) -> dict[str, object]:
    mutator, replacement = mutant.get("mutatorName"), mutant.get("replacement")
    return {
        "path": path,
        "line": line,
        "mutator": str(mutator)[:100] if mutator is not None else "",
        "replacement": str(replacement)[:200] if replacement is not None else "",
    }


def by_folder(ranges: Ranges) -> tuple[dict[str, Ranges], list[str]]:
    """The ranges of each Stryker folder, and the changed files no folder measures."""
    folders: dict[str, Ranges] = {}
    unmeasured: list[str] = []
    for path, spans in sorted(ranges.items()):
        folder = stryker_folder(path) if PurePosixPath(path).suffix in JS_SUFFIXES else None
        if folder is None:
            unmeasured.append(path)
        else:
            folders.setdefault(folder, {})[path] = spans
    return folders, unmeasured


def not_run(ranges: Ranges, result: dict[str, object]) -> str:
    tool = python_tool() if any(path.endswith(".py") for path in ranges) else ""
    result["tool"] = tool
    if tool:
        setup = "needs a per-repo setup this run does not make"
        return f"{tool} {setup}: run /test-strength on the PR"
    return "no mutation tool found in the repo"


def run_folder(folder: str, ranges: Ranges, *, budget: float, tally: Tally) -> str:
    """Measure one folder; its note (empty when clean). BudgetSpentError past the budget."""
    code = run_stryker(folder, ranges, budget)
    if code is None:
        return f"npx could not run in {folder}"
    if not read_report(folder, ranges, tally):
        return (
            f"stryker exited {code} in {folder} without a report"
            if code
            else (f"the stryker report could not be read in {folder}")
        )
    tally.measured += 1
    return f"stryker exited {code} in {folder} (its break threshold)" if code else ""


def measure(ranges: Ranges, budget: int, result: dict[str, object]) -> str:
    """Run Stryker in each folder that has it; the reason naming what was not measured."""
    folders, unmeasured = by_folder(ranges)
    if not folders:
        return not_run(ranges, result)
    result["tool"] = "stryker"
    tally, notes, deadline = Tally(), [], time.monotonic() + budget
    made = [
        path
        for folder in folders
        for path in (Path(folder) / "reports", Path(folder) / ".stryker-tmp")
        if not path.exists()
    ]
    before = tracked_changes()
    try:
        for folder, spans in sorted(folders.items()):
            try:
                left_s = max(0.0, deadline - time.monotonic())
                note = run_folder(folder, spans, budget=left_s, tally=tally)
            except BudgetSpentError:
                notes.append(f"inconclusive: stryker ran past its {budget} s budget in {folder}")
                unmeasured += [
                    path for name, rest in folders.items() if name > folder for path in rest
                ]
                break
            notes += [note] if note else []
    finally:
        for path in made:
            shutil.rmtree(path, ignore_errors=True)
    left = sorted(tracked_changes() - before)
    if left:
        raise StrengthError(f"the tool left {', '.join(left[:10])} changed")
    tally.fill(result)
    if unmeasured:
        notes.append(f"not measured: {', '.join(sorted(unmeasured)[:20])}")
    return "; ".join(notes)


def parse(argv: list[str]) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(prog="strength.py")
    parser.add_argument("--base", required=True)
    parser.add_argument("--budget", required=True)
    args = parser.parse_args(argv)
    budget = args.budget
    if not COMMIT.fullmatch(args.base):
        problem = f"the base is not a commit id: {args.base!r}"
    elif not (budget.isascii() and budget.isdecimal() and 0 < int(budget) <= MAX_BUDGET):
        problem = f"the budget is not 1 to {MAX_BUDGET} seconds: {budget!r}"
    else:
        return args
    print(f"strength.py: {problem}", file=sys.stderr)
    return None


def main(argv: list[str]) -> int:
    args = parse(argv)
    if args is None:
        return 2
    try:
        files = touched(args.base)
        result = empty(files)
        ranges = changed(args.base) if files else {}
        if not files:
            result["reason"] = "no commit after the bump"
        elif not ranges:
            result["reason"] = "no source line changed after the bump (tests only)"
        else:
            result["reason"] = measure(ranges, int(args.budget), result)
    except StrengthError as error:
        print(f"strength.py: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
