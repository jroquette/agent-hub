# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run the repo's check at a PR's head, in a throwaway worktree; print the result as JSON, exit 0.

``check.py --path <clone> --head <sha> --command <check> --fork true|false [--timeout <s>]``:
``command`` is the repo's ``check`` from ``hub.json``. It is never run for a fork (``not_run``), so
only a same-repo author's code runs, and the owner starts every run by hand. Otherwise git adds a
detached worktree of ``head`` (the already fetched object, no branch, hooks off) under a new
temporary folder, and ``bash -c <command>`` runs there with no stdin, in its own process group, and
an environment built from nothing: ``PATH``, ``LANG``, ``HOME`` and ``TMPDIR`` in the temporary
folder, plus the parent's proxy and CA variables (no token of any kind). After ``--timeout`` seconds
(2400), and once the check ends, the whole group is killed. The worktree and the folder are removed
in every case. Residual risk: the command can still read the owner's files by absolute path and
reach the network.

The output: ``{"status": passed|failed|timeout|not_run|error, "exit_code", "tail", "reason",
"command"}``, ``tail`` the last ``TAIL_CHARS`` characters of the output's last ``TAIL_BYTES`` bytes,
without control characters or backtick fences. Bad arguments exit 2.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO

TAIL_CHARS = 4000
TAIL_BYTES = 16384
REASON_CHARS = 1000
SHA = re.compile(r"[0-9a-f]{40}")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
BACKTICKS = re.compile(r"`{3,}")
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")
# Kept from the parent: reaching the network through the owner's proxy, and its CAs.
PASSED_THROUGH = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "GIT_SSL_CAINFO",
)


def clean(text: str) -> str:
    return BACKTICKS.sub("`", CONTROL.sub("", text.replace("\r\n", "\n")))


def child_env(environ: dict[str, str], tmp: Path) -> dict[str, str]:
    """The check's environment, from nothing: no token, home and temp in ``tmp``."""
    (tmp / "home").mkdir(exist_ok=True)
    (tmp / "tmp").mkdir(exist_ok=True)
    env = {
        "PATH": environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "HOME": str(tmp / "home"),
        "TMPDIR": str(tmp / "tmp"),
    }
    env.update({name: environ[name] for name in PASSED_THROUGH if name in environ})
    return env


def tail(output: IO[bytes]) -> str:
    """The last characters of ``output``, read from its last ``TAIL_BYTES`` bytes only."""
    size = output.seek(0, os.SEEK_END)
    output.seek(max(0, size - TAIL_BYTES))
    return clean(output.read().decode("utf-8", errors="replace"))[-TAIL_CHARS:]


def result(
    status: str, command: str, *, exit_code: int | None = None, **more: str
) -> dict[str, object]:
    return {
        "status": status,
        "exit_code": exit_code,
        "tail": more.get("tail", ""),
        "reason": clean(more.get("reason", ""))[:REASON_CHARS],
        "command": command,
    }


def git(path: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - git with fixed arguments, hooks off
        [*GIT, "-C", str(path), *args],
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def kill_group(pid: int) -> None:
    """Kill the check's process group; one already gone is fine."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


def run_check(
    command: str, worktree: Path, *, env: dict[str, str], timeout: float
) -> dict[str, object]:
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(  # noqa: S603 - the repo's configured check, by design
            ["bash", "-c", command],  # noqa: S607 - bash from PATH, as hub run's gate
            cwd=worktree,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group(child.pid)
            child.wait()
            reason = f"the check ran over {timeout:g} s and was stopped"
            return result("timeout", command, tail=tail(output), reason=reason)
        # What the check left running (a server, a watcher) never outlives it.
        kill_group(child.pid)
        status = "passed" if code == 0 else "failed"
        return result(status, command, exit_code=code, tail=tail(output))


def checked(given: argparse.Namespace) -> dict[str, object]:
    command, path = given.command, Path(given.path)
    if given.fork == "true":
        return result(
            "not_run", command, reason="the PR comes from a fork: its check never runs here"
        )
    if not command.strip():
        return result("not_run", command, reason="the repo has no check in hub.json")
    if git(path, "cat-file", "-e", f"{given.head}^{{commit}}").returncode != 0:
        return result("error", command, reason="the head is not in the clone; fetch again")
    tmp = Path(tempfile.mkdtemp(prefix="review-incoming-check-"))
    worktree = tmp / "wt"
    try:
        added = git(path, "worktree", "add", "--detach", str(worktree), given.head)
        if added.returncode != 0:
            reason = "git could not add a worktree: " + added.stderr.decode(errors="replace")
            return result("error", command, reason=reason)
        env = child_env(dict(os.environ), tmp)
        return run_check(command, worktree, env=env, timeout=given.timeout)
    finally:
        git(path, "worktree", "remove", "--force", str(worktree))
        git(path, "worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check.py")
    parser.add_argument("--path", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--fork", required=True)
    parser.add_argument("--timeout", type=float, default=2400.0)
    given = parser.parse_args(argv)
    if not SHA.fullmatch(given.head):
        print("check.py: head must be a full commit sha", file=sys.stderr)
        return 2
    if given.fork not in {"true", "false"}:
        print("check.py: fork must be true or false", file=sys.stderr)
        return 2
    if not given.timeout > 0:
        print("check.py: timeout must be a positive number of seconds", file=sys.stderr)
        return 2
    print(json.dumps(checked(given), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
