# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run the repo's check on the exact release commit and print its result as JSON; exit 0 either way.

``exact_check.py <command> --sha <40 hex>`` runs in the release worktree (the node's cwd). First
``HEAD`` must be the release commit and ``git status --porcelain --untracked-files=all`` empty:
a clean checkout at that commit is that commit. Then ``command`` (the repo's ``check`` from
``hub.json``) runs through ``bash -c``, its stdout and stderr to a log file in the temporary
folder; then both conditions are checked again, so a check that moves ``HEAD`` or changes a file
did not check the release commit.

Prints ``{"sha", "passed", "exit_code", "log", "tail", "problem"}``: ``tail`` the log's last
``TAIL_CHARS`` characters, ``problem`` why it did not pass (empty when it did). A red check is
data, not a failed node. A dirty checkout or another ``HEAD`` before the check exits 1, a bad SHA
exits 2, each with the reason on stderr.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile

PROG = "exact_check.py"
TAIL_CHARS = 4000
# A UTF-8 character is at most 4 bytes: this many bytes always hold the last TAIL_CHARS.
TAIL_BYTES = 4 * TAIL_CHARS
GIT_TIMEOUT = 120
SHA = re.compile(r"[0-9a-f]{40}")


class FailedError(Exception):
    """The checkout is not the clean release commit, or git failed: exit 1."""


def _git(*args: str) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - git from PATH, arguments the script built
            ["git", *args],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FailedError(f"git {args[0]} failed: {error}") from None
    if done.returncode != 0:
        raise FailedError(f"git {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def problem_with(sha: str) -> str:
    """Why the checkout is not the clean release commit, or empty."""
    head = _git("rev-parse", "HEAD").strip()
    if head != sha:
        return f"HEAD is {head}, not the release commit {sha}"
    dirty = _git("status", "--porcelain", "--untracked-files=all").strip()
    if dirty:
        return f"the checkout is not clean: {' '.join(dirty.split())[:400]}"
    return ""


def run_check(command: str) -> tuple[int, str, str]:
    """The check's exit code, its log's path and its tail."""
    with tempfile.NamedTemporaryFile(prefix="release-check-", suffix=".log", delete=False) as log:
        # The repo's own gate, as hub run runs it: a shell command line from hub.json.
        done = subprocess.run(  # noqa: S603 - the repo's configured check, by design
            ["bash", "-c", command],  # noqa: S607 - bash from PATH, as hub run's gate
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    with open(log.name, "rb") as written:
        size = written.seek(0, 2)
        written.seek(max(0, size - TAIL_BYTES))
        tail = written.read().decode(errors="replace")[-TAIL_CHARS:]
    return done.returncode, log.name, tail


def checked(command: str, sha: str) -> dict[str, object]:
    before = problem_with(sha)
    if before:
        raise FailedError(f"{before}; the check runs only on the clean release commit")
    code, log, tail = run_check(command)
    after = problem_with(sha)
    problem = f"the check exited {code}" if code != 0 else ""
    if after:
        problem = "; ".join(part for part in (problem, f"after the check, {after}") if part)
    return {
        "sha": sha,
        "passed": not problem,
        "exit_code": code,
        "log": log,
        "tail": tail,
        "problem": problem,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("command")
    parser.add_argument("--sha", required=True)
    given = parser.parse_args(argv)
    if not SHA.fullmatch(given.sha):
        print(f"{PROG}: --sha must be a full commit SHA", file=sys.stderr)
        return 2
    try:
        found = checked(given.command, given.sha)
    except FailedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
