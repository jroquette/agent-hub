# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run each hypothesis's read-only check; print the results as one JSON object.

``check.py --repos <evidence repos JSON>`` with the hypotheses reply (``{"hypotheses": [...]}``)
on stdin, run in the hub. The hypotheses run in rank order; each check runs, from the root of a
detached worktree of its repo (``../<dir>``) at the evidence's ``head``, made under one
``tempfile.mkdtemp()`` when first needed and removed at the end, so the owner's checkouts are
never the cwd and stay as they were. Each check gets ``--timeout`` seconds (60; its process
group is killed after), and all of them ``--budget`` seconds (300; the rest are refused). Its
output goes to a temporary file, of which only the last ``TAIL_BYTES`` are read.

Output: ``{results: [{id, rank, repo, status, exit_code, reason, tail}], confirmed, mitigations,
menu}``. ``status`` is ``confirmed`` (exit 0), ``failed`` (another exit), ``refused`` (the rules
below, or the budget), ``timeout`` or ``error`` (an unknown repo, a duplicate id, a head that
cannot be checked out); only ``confirmed`` confirms. ``mitigations`` counts the confirmed
hypotheses that propose one; ``menu`` lists each hypothesis's status, each such mitigation as
``H<n>: <summary> (undo: <undo>)``, and the two ``hub workflow respond`` commands of the gate.
Exit 0 with the JSON, whatever the checks did; exit 2 on malformed input.

A check is an argv list that an agent wrote after reading untrusted text, so it runs only when
``refusal`` finds nothing: no shell; ``argv[0]`` one of ``PROGRAMS``; for git, ``argv[1]`` one of
``GIT_SUBCOMMANDS`` (no global option before it) and no option starting with one of
``GIT_OPTIONS`` (nor an abbreviation of one, nor ``O`` in a short-option cluster:
``git grep -O`` runs a pager);
for tail, no follow option; every argument, and its part after the first ``=``, relative and
inside the checkout (no leading ``/`` or ``~``, no ``..`` segment, no ``/`` or ``~`` in a
short-option cluster); 1 to ``MAX_ELEMENTS`` elements of at most ``MAX_ELEMENT`` characters,
none holding a control character. git runs with ``GIT_PREFIX`` (no pager, fsmonitor, hooks or
external diff), and its diff family without ext-diff or textconv. ``child_env`` builds the
child's environment from nothing, so no token or credential of the parent passes.

Residual risk (accepted; the repos are the project's own and the record stays local): cat, head
and grep follow a symlink committed in the repo to outside the checkout, and the repo's own
``.git/config`` still applies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

PROGRAMS = frozenset({"git", "grep", "test", "ls", "cat", "head", "tail", "wc"})
GIT_SUBCOMMANDS = frozenset(
    {
        "log",
        "show",
        "diff",
        "grep",
        "blame",
        "ls-files",
        "ls-tree",
        "cat-file",
        "rev-parse",
        "merge-base",
        "rev-list",
    }
)
# Options that run another program, write a file or leave the repository.
GIT_OPTIONS = (
    "output",
    "open-files-in-pager",
    "ext-diff",
    "textconv",
    "filters",
    "exec",
    "upload-pack",
    "git-dir",
    "work-tree",
    "no-index",
)
GIT_PREFIX = (
    "git",
    "-c",
    "core.pager=cat",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "diff.external=",
    "--no-pager",
)
# Turned off explicitly where git turns them on by default.
GIT_DEFAULTS_OFF = {
    "log": ("--no-ext-diff", "--no-textconv"),
    "show": ("--no-ext-diff", "--no-textconv"),
    "diff": ("--no-ext-diff", "--no-textconv"),
    "blame": ("--no-textconv",),
}
MAX_ELEMENTS = 16
MAX_ELEMENT = 256
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
TAIL_CHARS = 1000
# A UTF-8 character is at most 4 bytes: this many bytes always hold the last TAIL_CHARS.
TAIL_BYTES = 4 * TAIL_CHARS
MAX_HYPOTHESES = 5
MAX_REASON = 200
MAX_MENU = 4096
DIR = re.compile(r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*")
SHA = re.compile(r"[0-9a-f]{40}")
DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"
WORKTREE_TIMEOUT = 120
WORKTREE_GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")


def _long_name(argument: str) -> str | None:
    """A long option's name (``--name[=value]``), else ``None``; ``--`` alone has none."""
    if not argument.startswith("--") or argument == "--":
        return None
    return argument[2:].split("=", 1)[0]


def _cluster(argument: str) -> str | None:
    """A short-option cluster's letters and attached value (``-nO``), else ``None``."""
    if argument.startswith("-") and not argument.startswith("--") and len(argument) > 1:
        return argument[1:]
    return None


def _outside(argument: str) -> bool:
    """Whether ``argument``, or its part after the first ``=``, may leave the checkout."""
    parts = [argument]
    if "=" in argument:
        parts.append(argument.split("=", 1)[1])
    for part in parts:
        if part.startswith(("/", "~")) or ".." in part.split("/"):
            return True
    cluster = _cluster(argument)
    return cluster is not None and ("/" in cluster or "~" in cluster)


def _shape_refusal(argv: object) -> str | None:
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return "refused: the check is not an argv list of strings"
    if not 1 <= len(argv) <= MAX_ELEMENTS:
        return f"refused: the check has {len(argv)} elements, not 1 to {MAX_ELEMENTS}"
    for item in argv:
        if len(item) > MAX_ELEMENT:
            return f"refused: an element is over {MAX_ELEMENT} characters"
        if CONTROL.search(item):
            return "refused: an element holds a control character"
    return None


def _git_refusal(argv: list[str]) -> str | None:
    if len(argv) < 2 or argv[1] not in GIT_SUBCOMMANDS:
        return "refused: not an allowed git subcommand (log, show, diff, grep, blame, ...)"
    for argument in argv[2:]:
        name = _long_name(argument)
        if name and any(
            option.startswith(name) or name.startswith(option) for option in GIT_OPTIONS
        ):
            return f"refused: git option {argument.split('=', 1)[0][:60]!r}"
        cluster = _cluster(argument)
        if cluster is not None and "O" in cluster:
            return "refused: git option -O (runs a pager)"
    return None


def _tail_refusal(argv: list[str]) -> str | None:
    for argument in argv[1:]:
        name = _long_name(argument)
        cluster = _cluster(argument)
        if (name and "follow".startswith(name)) or (cluster and ("f" in cluster or "F" in cluster)):
            return "refused: tail may not follow a file"
    return None


def refusal(argv: object) -> str | None:
    """Why the check ``argv`` may not run, or ``None`` when it may (at most 200 characters)."""
    shaped = _shape_refusal(argv)
    if shaped is not None or not isinstance(argv, list):
        return shaped
    if argv[0] not in PROGRAMS:
        return f"refused: program {argv[0][:40]!r} is not one of {', '.join(sorted(PROGRAMS))}"
    if argv[0] == "git" and (refused := _git_refusal(argv)) is not None:
        return refused
    if argv[0] == "tail" and (refused := _tail_refusal(argv)) is not None:
        return refused
    for argument in argv[1:]:
        if _outside(argument):
            return f"refused: path {argument[:60]!r} leaves the checkout"
    return None


def command(argv: list[str]) -> list[str]:
    """The argv to run for an allowed check: git with its safe prefix, others as they are."""
    if argv[0] != "git":
        return list(argv)
    return [*GIT_PREFIX, argv[1], *GIT_DEFAULTS_OFF.get(argv[1], ()), *argv[2:]]


def child_env(path: str, home: str) -> dict[str, str]:
    """The check's whole environment, built from nothing: no token or credential passes."""
    return {
        "PATH": path,
        "LANG": "C.UTF-8",
        "HOME": home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "PAGER": "cat",
    }


class BadInputError(Exception):
    """Input this script refuses: exit 2 with its message."""


@dataclass
class Sandbox:
    """The throwaway worktrees of one run, under one temporary folder, made when first needed."""

    heads: dict[str, str]
    timeout: float
    deadline: float
    root: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="incident-check-")))
    made: dict[str, Path | None] = field(default_factory=dict)

    def env(self) -> dict[str, str]:
        return child_env(os.environ.get("PATH") or DEFAULT_PATH, str(self.root))

    def git(self, repo: str, *args: str) -> bool:
        """``git <args>`` in the owner's checkout of ``repo``, hooks off; whether it passed."""
        try:
            done = subprocess.run(  # noqa: S603 - git from PATH, fixed worktree subcommands
                [*WORKTREE_GIT, *args],
                cwd=Path("..") / repo,
                env=self.env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=WORKTREE_TIMEOUT,
                check=False,
            )
        except OSError, subprocess.SubprocessError:
            return False
        return done.returncode == 0

    def worktree(self, repo: str) -> Path | None:
        """The worktree of ``repo`` at its evidence head, or ``None`` when it cannot be made."""
        if repo not in self.made:
            path = self.root / repo
            added = self.git(
                repo, "worktree", "add", "--quiet", "--detach", str(path), self.heads[repo]
            )
            self.made[repo] = path if added else None
        return self.made[repo]

    def close(self) -> None:
        for repo, path in self.made.items():
            if path is not None:
                self.git(repo, "worktree", "remove", "--force", str(path))
                self.git(repo, "worktree", "prune")
        shutil.rmtree(self.root, ignore_errors=True)


def tail_of(output: IO[bytes]) -> str:
    size = output.seek(0, 2)
    output.seek(max(0, size - TAIL_BYTES))
    text = output.read().decode(errors="replace")[-TAIL_CHARS:]
    return CONTROL.sub(lambda match: match.group() if match.group() in "\n\t" else "", text)


def execute(argv: list[str], cwd: Path, sandbox: Sandbox) -> tuple[int | None, str]:
    """Run an allowed check: its exit code (``None`` on a timeout) and its output's tail."""
    limit = min(sandbox.timeout, sandbox.deadline - time.monotonic())
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(  # noqa: S603 - an argv on the allow-list, no shell
            command(argv),
            cwd=cwd,
            env=sandbox.env(),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code: int | None = child.wait(timeout=max(limit, 0))
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            code = None
        return code, tail_of(output)


def a_result(hypothesis: dict[str, Any], status: str, reason: str = "") -> dict[str, Any]:
    rank = hypothesis.get("rank")
    return {
        "id": str(hypothesis.get("id", ""))[:8],
        "rank": rank if isinstance(rank, int) and not isinstance(rank, bool) else 0,
        "repo": str(hypothesis.get("repo", ""))[:64],
        "status": status,
        "exit_code": None,
        "reason": CONTROL.sub("", reason)[:MAX_REASON],
        "tail": "",
    }


def check_one(hypothesis: dict[str, Any], sandbox: Sandbox, seen: set[str]) -> dict[str, Any]:
    ident, repo = hypothesis.get("id"), hypothesis.get("repo")
    if ident in seen:
        return a_result(hypothesis, "error", f"error: duplicate id {str(ident)[:8]}")
    seen.add(str(ident))
    if not isinstance(repo, str) or repo not in sandbox.heads:
        return a_result(hypothesis, "error", f"error: unknown repo {str(repo)[:64]!r}")
    argv = hypothesis.get("check")
    if (refused := refusal(argv)) is not None or not isinstance(argv, list):
        return a_result(hypothesis, "refused", refused or "refused")
    if time.monotonic() >= sandbox.deadline:
        return a_result(hypothesis, "refused", "refused: budget - the node's checks are spent")
    cwd = sandbox.worktree(repo)
    if cwd is None:
        return a_result(hypothesis, "error", f"error: cannot check out {sandbox.heads[repo][:7]}")
    try:
        code, tail = execute(argv, cwd, sandbox)
    except OSError as error:
        return a_result(hypothesis, "error", f"error: cannot run {argv[0]}: {error.strerror}")
    status = "timeout" if code is None else "confirmed" if code == 0 else "failed"
    return a_result(hypothesis, status) | {"exit_code": code, "tail": tail}


def clean(value: object, limit: int) -> str:
    return CONTROL.sub(" ", str(value))[:limit]


def menu_of(hypotheses: list[dict[str, Any]], results: list[dict[str, Any]]) -> str:
    """The gate's menu: each status, each confirmed mitigation, the two respond commands."""
    run = os.environ.get("AGENT_HUB_RUN_ID") or "<run>"
    lines = []
    for hypothesis, result in zip(hypotheses, results, strict=True):
        lines.append(f"{result['id']} {result['status']}")
        mitigation = hypothesis.get("mitigation")
        if result["status"] == "confirmed" and isinstance(mitigation, dict):
            summary = clean(mitigation.get("summary", ""), 300)
            undo = clean(mitigation.get("undo", ""), 300)
            lines.append(f"{result['id']}: {summary} (undo: {undo})")
    commands = [
        f"Record: hub workflow respond {run} --choice record --text H<n> (or your own mitigation)",
        f"None: hub workflow respond {run} --choice none",
    ]
    room = MAX_MENU - sum(len(line) + 1 for line in commands)
    kept: list[str] = []
    for line in lines:
        if sum(len(item) + 1 for item in kept) + len(line) + 1 > room:
            break
        kept.append(line)
    return "\n".join([*kept, *commands])


def read_input(repos: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    try:
        reply, evidence = json.loads(sys.stdin.read()), json.loads(repos)
    except ValueError as error:
        raise BadInputError(f"not JSON: {error}") from None
    hypotheses = reply.get("hypotheses") if isinstance(reply, dict) else None
    if not isinstance(hypotheses, list) or not all(isinstance(h, dict) for h in hypotheses):
        raise BadInputError('stdin is not {"hypotheses": [objects]}')
    if not isinstance(evidence, list):
        raise BadInputError("--repos is not the evidence's list of repos")
    heads = {
        repo["dir"]: repo["head"]
        for repo in evidence
        if isinstance(repo, dict)
        and isinstance(repo.get("dir"), str)
        and DIR.fullmatch(repo["dir"])
        and isinstance(repo.get("head"), str)
        and SHA.fullmatch(repo["head"])
    }
    ranked = sorted(hypotheses, key=lambda h: h["rank"] if isinstance(h.get("rank"), int) else 99)
    return ranked[:MAX_HYPOTHESES], heads


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check.py")
    parser.add_argument("--repos", required=True)
    # For tests: one check's limit and all checks' budget, in seconds.
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--budget", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        hypotheses, heads = read_input(args.repos)
    except BadInputError as error:
        print(f"check.py: {error}", file=sys.stderr)
        return 2
    sandbox = Sandbox(heads, args.timeout, time.monotonic() + args.budget)
    seen: set[str] = set()
    try:
        results = [check_one(hypothesis, sandbox, seen) for hypothesis in hypotheses]
    finally:
        sandbox.close()
    confirmed = [h for h, r in zip(hypotheses, results, strict=True) if r["status"] == "confirmed"]
    output = {
        "results": results,
        "confirmed": len(confirmed),
        "mitigations": sum(isinstance(h.get("mitigation"), dict) for h in confirmed),
        "menu": menu_of(hypotheses, results),
    }
    text = json.dumps(output, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(text.encode())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
