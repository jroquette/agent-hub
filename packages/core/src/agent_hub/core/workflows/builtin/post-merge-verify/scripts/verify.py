# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run each selected AC's verification once at the commit and print the results as one JSON object.

``verify.py [--timeout <seconds>] [--budget <seconds>]``, run in the hub, reads ``selection.py``'s
JSON on stdin and each AC's ``verification`` again from ``brain/features/<feature>/features.json``.
A verification that cannot run after the merge is never run and is listed apart, with its reason:
``absolute path`` (a path from ``/`` other than ``/dev/...``, ``/tmp/...`` or the default of a
``${WT:-...}`` expansion), ``worktree path`` (``.claude/worktrees/``), ``origin diff range``
(``origin/<ref>..``) or ``too long`` (over ``MAX_COMMAND_BYTES``). The others run one at a time,
once each and never again, through ``bash -c`` in a throwaway detached ``git worktree`` of the
repo at ``sha``, made in a new temporary folder and removed afterwards, so the repo's checkout is
left as it was; ``WT`` is that worktree's path, stdin is empty, and a command still running after
``--timeout`` (default 600 s) is killed with its process group. Once ``--budget`` (default
39600 s) is spent, the rest are counted ``not_run``.

Output: ``{"sha", "counts": {"selected", "passed", "failed", "timed_out", "errors", "cannot_run",
"not_run"}, "broken", "failures": [{"feature", "ac", "command", "status", "exit_code", "tail",
"since"}], "more_failed", "cannot_run": [{"feature", "ac", "reason", "command"}],
"more_cannot_run"}``. ``status`` is ``failed`` (a non-zero exit), ``timeout`` or ``error`` (the
AC could not be read again); ``broken`` counts the three. ``failures`` holds the first ones within
``FAILURES_BYTES``, ``more_failed`` the rest's ``<feature> <ac>``; ``since`` is the first date of
the AC's evidence, its last pass. The output stays within ``MAX_OUTPUT_BYTES``. Bad input exits
2; a worktree that cannot be made exits 1. Both say why on stderr.
"""

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

# A tuple, not an except list: ``uv run`` may run this on Python 3.12.
READ_ERRORS = (OSError, ValueError)
USAGE = "usage: verify.py [--timeout <seconds>] [--budget <seconds>] < selection.json"
FEATURES = Path("brain/features")
TIMEOUT = 600
BUDGET = 11 * 3600
MAX_COMMAND_BYTES = 8192
MAX_RECORD_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024
TAIL_BYTES = 2048
TAIL_CHARS = 500
COMMAND_CHARS = 200
MAX_FAILURES = 50
FAILURES_BYTES = 100_000
MAX_MORE_FAILED = 2000
MAX_CANNOT_RUN = 500
MAX_OUTPUT_BYTES = 480 * 1024

# ``${WT:-/abs/path}``: the path is a fallback, as WT is always set here.
WT_DEFAULT = re.compile(r"\$\{WT:-[^}]*\}")
# A ``/`` that starts a word after a blank, a quote, ``=``, ``:``, ``(`` or ``-``; not
# ``/dev/null``, ``/dev/stdin|stdout|stderr`` or ``/tmp``.
ABSOLUTE = re.compile(r"(?:^|[\s'\"=:(-])/(?!dev/(?:null|stdin|stdout|stderr)\b|tmp\b)\w")
ORIGIN_RANGE = re.compile(r"origin/[\w./-]*?\.\.")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def cannot_run(command: str) -> str | None:
    """Why ``command`` cannot run at the merge commit on another machine, or ``None``."""
    if len(command.encode(errors="surrogatepass")) > MAX_COMMAND_BYTES:
        return "too long"
    portable = WT_DEFAULT.sub("$WT", command)
    if ".claude/worktrees/" in portable:
        return "worktree path"
    if ORIGIN_RANGE.search(portable):
        return "origin diff range"
    if ABSOLUTE.search(portable):
        return "absolute path"
    return None


def classify(returncode: int | None, *, timed_out: bool) -> str:
    """A run's status: ``passed``, ``failed`` or ``timeout``."""
    if timed_out:
        return "timeout"
    return "passed" if returncode == 0 else "failed"


class BadInputError(Exception):
    """The input is not a selection this script can read."""


class WorktreeError(Exception):
    """The commit cannot be checked out in a throwaway worktree."""


@dataclass
class Results:
    sha: str
    counts: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(
            ("selected", "passed", "failed", "timed_out", "errors", "cannot_run", "not_run"), 0
        )
    )
    failures: list[dict[str, object]] = field(default_factory=list)
    cannot_run: list[dict[str, str]] = field(default_factory=list)

    def failed(self, entry: dict[str, object]) -> None:
        kinds = {"failed": "failed", "timeout": "timed_out"}
        self.counts[kinds.get(str(entry["status"]), "errors")] += 1
        self.failures.append(entry)

    def output(self) -> dict[str, object]:
        detailed, more = fit_failures(self.failures)
        listed = self.cannot_run[:MAX_CANNOT_RUN]
        found: dict[str, object] = {
            "sha": self.sha,
            "counts": self.counts,
            "broken": len(self.failures),
            "failures": detailed,
            "more_failed": more[:MAX_MORE_FAILED],
            "cannot_run": listed,
            "more_cannot_run": len(self.cannot_run) - len(listed),
        }
        return fit_output(found)


def encoded(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def fit_failures(failures: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[str]]:
    """The failures detailed within ``MAX_FAILURES`` and ``FAILURES_BYTES``; the rest's ids."""
    detailed: list[dict[str, object]] = []
    size = 2
    for entry in failures:
        size += encoded(entry) + 1
        if len(detailed) == MAX_FAILURES or size > FAILURES_BYTES:
            break
        detailed.append(entry)
    rest = failures[len(detailed) :]
    return detailed, [f"{entry['feature']} {entry['ac']}" for entry in rest]


def fit_output(found: dict[str, object]) -> dict[str, object]:
    """``found`` with its last listed cannot-run entries, then failure ids, dropped to fit."""
    listed, more = found["cannot_run"], found["more_failed"]
    if not isinstance(listed, list) or not isinstance(more, list):
        return found
    while encoded(found) > MAX_OUTPUT_BYTES and (listed or more):
        if listed:
            listed.pop()
            found["more_cannot_run"] = int(str(found["more_cannot_run"])) + 1
        else:
            more.pop()
    return found


def options(argv: list[str]) -> tuple[float, float]:
    given = dict(zip(argv[::2], argv[1::2], strict=False))
    if len(argv) % 2 or not set(given) <= {"--timeout", "--budget"}:
        raise BadInputError(USAGE)
    try:
        timeout = float(given.get("--timeout", TIMEOUT))
        budget = float(given.get("--budget", BUDGET))
    except ValueError:
        raise BadInputError(USAGE) from None
    if timeout <= 0 or budget < 0:
        raise BadInputError(USAGE)
    return timeout, budget


def read_selection(stream: IO[str]) -> tuple[str, Path, list[object]]:
    """The selection's commit, repo and selected ACs."""
    try:
        data = json.loads(stream.read(MAX_INPUT_BYTES + 1))
    except ValueError:
        raise BadInputError("stdin is not a selection's JSON") from None
    if not (
        isinstance(data, dict)
        and isinstance(data.get("sha"), str)
        and isinstance(data.get("repo_path"), str)
        and isinstance(data.get("selected"), list)
    ):
        raise BadInputError("stdin is not a selection: sha, repo_path and selected are needed")
    return data["sha"], Path(data["repo_path"]), data["selected"]


def find_ac(feature: str, ac_id: str) -> dict[str, object] | str:
    """The AC ``ac_id`` of the record ``feature``, or why it cannot be read again."""
    root = FEATURES.resolve()
    path = (root / feature / "features.json").resolve()
    if not path.is_relative_to(root):
        return "the feature leaves brain/features"
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            return "the record is too large"
        record = json.loads(path.read_text(encoding="utf-8"))
    except READ_ERRORS:
        return "the record cannot be read"
    acs = record.get("acs") if isinstance(record, dict) else None
    for ac in acs if isinstance(acs, list) else []:
        if (
            isinstance(ac, dict)
            and ac.get("id") == ac_id
            and isinstance(ac.get("verification"), str)
        ):
            return ac
    return f"no {ac_id} with a verification in the record"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - git worktree with fixed arguments
        ["git", "-C", str(repo), *args],  # noqa: S607 - git from PATH
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


@contextlib.contextmanager
def worktree(repo: Path, sha: str) -> Iterator[Path]:
    """A detached worktree of ``repo`` at ``sha`` in a new temporary folder, removed afterwards."""
    # A run killed before its cleanup (a node timeout, a resume) leaves an entry behind.
    git(repo, "worktree", "prune")
    folder = Path(tempfile.mkdtemp(prefix="post-merge-verify-"))
    path = folder / "checkout"
    try:
        made = git(repo, "worktree", "add", "--detach", "--quiet", str(path), sha)
        if made.returncode != 0:
            detail = made.stderr.decode(errors="replace").strip()[-300:]
            raise WorktreeError(f"cannot check out {sha[:12]}: {detail}")
        yield path
    finally:
        git(repo, "worktree", "remove", "--force", str(path))
        shutil.rmtree(folder, ignore_errors=True)
        git(repo, "worktree", "prune")


def run_once(command: str, *, cwd: Path, timeout: float) -> tuple[int | None, bool, str]:
    """``command``'s exit code (``None`` on a timeout), whether it timed out, its output's tail."""
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(  # noqa: S603 - the AC's recorded verification, by design
            ["bash", "-c", command],  # noqa: S607 - bash from PATH, as the verification's author ran it
            cwd=cwd,
            env={**os.environ, "WT": str(cwd)},
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
            # The whole group, so nothing the command started outlives it.
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        size = output.seek(0, 2)
        output.seek(max(0, size - TAIL_BYTES))
        tail = output.read().decode(errors="replace")[-TAIL_CHARS:]
    return (None if timed_out else process.returncode), timed_out, tail


def since_of(ac: dict[str, object]) -> str:
    found = DATE.search(str(ac.get("evidence") or ""))
    return found.group(0) if found else ""


def triage(selected: list[object], results: Results) -> list[tuple[str, str, str, str]]:
    """The runnable ``(feature, ac, command, since)``; the others go into ``results``."""
    runnable = []
    for item in selected:
        if not isinstance(item, dict):
            raise BadInputError("a selected item is not an object")
        feature, ac_id = str(item.get("feature", "")), str(item.get("ac", ""))
        results.counts["selected"] += 1
        ac = find_ac(feature, ac_id)
        if isinstance(ac, str):
            results.failed(
                entry(feature, ac_id, command="", status="error", exit_code=None, tail=ac, since="")
            )
            continue
        command = str(ac["verification"])
        if reason := cannot_run(command):
            results.counts["cannot_run"] += 1
            flagged = {"feature": feature, "ac": ac_id, "reason": reason}
            results.cannot_run.append(flagged | {"command": command[:COMMAND_CHARS]})
            continue
        runnable.append((feature, ac_id, command, since_of(ac)))
    return runnable


def entry(
    feature: str,
    ac: str,
    *,
    command: str,
    status: str,
    exit_code: int | None,
    tail: str,
    since: str,
) -> dict[str, object]:
    return {
        "feature": feature,
        "ac": ac,
        "command": command[:COMMAND_CHARS],
        "status": status,
        "exit_code": exit_code,
        "tail": tail[-TAIL_CHARS:],
        "since": since,
    }


def run_all(
    runnable: list[tuple[str, str, str, str]],
    results: Results,
    *,
    repo: Path,
    limits: tuple[float, float],
) -> None:
    timeout, budget = limits
    started = time.monotonic()
    with worktree(repo, results.sha) as path:
        for feature, ac_id, command, since in runnable:
            if time.monotonic() - started >= budget:
                results.counts["not_run"] += 1
                continue
            code, timed_out, tail = run_once(command, cwd=path, timeout=timeout)
            status = classify(code, timed_out=timed_out)
            if status == "passed":
                results.counts["passed"] += 1
            else:
                results.failed(
                    entry(
                        feature,
                        ac_id,
                        command=command,
                        status=status,
                        exit_code=code,
                        tail=tail,
                        since=since,
                    )
                )


def main(argv: list[str]) -> int:
    try:
        limits = options(argv)
        sha, repo, selected = read_selection(sys.stdin)
        results = Results(sha=sha)
        runnable = triage(selected, results)
    except BadInputError as error:
        print(f"verify.py: {error}", file=sys.stderr)
        return 2
    if runnable:
        if limits[1] <= 0:
            results.counts["not_run"] += len(runnable)
        else:
            try:
                run_all(runnable, results, repo=repo, limits=limits)
            except WorktreeError as error:
                print(f"verify.py: {error}", file=sys.stderr)
                return 1
    print(json.dumps(results.output(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
