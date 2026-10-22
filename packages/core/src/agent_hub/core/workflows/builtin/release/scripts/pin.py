# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The hub's platform pin: what ``hub sync`` rewrites at a new version, then the pin's commit.

``pin.py list --repo <platform checkout> --version X.Y.Z`` runs in the hub (the node's default
cwd). It adds a detached git worktree of the hub at its local ``origin/<default_branch>`` in a
temporary folder, sets that copy's ``platform.version`` to the new version and runs the
platform checkout's CLI there (``uv run --project <repo> --locked --all-packages hub sync
--check``, which renders the new version without fetching a release); the ``would <verb>
<path>`` lines are the list (``hub.lock`` aside). The worktree is removed at the end. Prints
``{"from", "version", "count", "files", "omitted", "conflicts", "text"}``: ``files`` at most
``MAX_FILES`` ``{verb, path}`` (the rest counted in ``omitted``), ``conflicts`` at most
``MAX_CONFLICTS`` lines of a conflict report (exit 3), ``text`` one ``<verb> <path>`` line per
listed file (``none`` when nothing changes).

``pin.py apply --worktree <hub worktree> --version X.Y.Z --issue <team>-<n>`` sets the pin in
that worktree, runs its ``./hub sync``, then ``./hub sync --check`` (it must say ``up to date``),
and commits everything once, ``chore(hub): bump platform to X.Y.Z (<issue>)``, with git hooks
off. Prints ``{"from", "version", "sha", "count", "files", "summary"}``; ``summary`` (the PR's
body, at most ``MAX_SUMMARY`` bytes) names the version, the tag and the files sync rewrote.

Both edit only the ``version`` value inside ``hub.json``'s ``platform`` object, as text, so the
file's layout stays. A bad argument or ``hub.json`` (larger than 1 MiB, not a JSON object, no
``platform.version``, no default branch in ``project``) exits 2; a git or CLI failure, a dirty hub
worktree or a sync still pending after ``apply`` exits 1. Both say why on stderr.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROG = "pin.py"
MAX_CONFIG_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_FILES = 500
MAX_CONFLICTS = 50
MAX_SUMMARY = 32 * 1024
CHILD_TIMEOUT = 900
GIT_TIMEOUT = 120
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
ISSUE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,15}-[0-9]{1,9}")
PLATFORM = re.compile(r'"platform"\s*:\s*\{')
PIN = re.compile(r'("version"\s*:\s*)"[^"\\]*"')
WOULD = re.compile(r"would (create|restore|update|delete) (.+)")
DONE = re.compile(r"(created|restored|updated|deleted) (.+)")
HUB_LOCK = "hub.lock"
# hub sync --check: up to date, a conflict, changes pending.
UP_TO_DATE, CONFLICT, PENDING = 0, 3, 4


class RefusedError(Exception):
    """Bad input: exit 2."""


class FailedError(Exception):
    """git, the CLI or the hub worktree failed: exit 1."""


def read_hub_json(path: Path) -> tuple[str, dict[str, object], str]:
    """The file's text, its JSON object and its ``platform.version``."""
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise RefusedError("hub.json: larger than 1 MiB")
        text = path.read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, ValueError) as error:
        raise RefusedError(f"hub.json: {error}") from None
    platform = value.get("platform") if isinstance(value, dict) else None
    pin = platform.get("version") if isinstance(platform, dict) else None
    if not isinstance(pin, str) or not isinstance(value, dict):
        raise RefusedError("hub.json: no platform.version")
    return text, value, pin


def set_pin(text: str, version: str) -> str:
    """``text`` with only the ``platform`` object's ``version`` value set to ``version``."""
    opened = PLATFORM.search(text)
    end = -1 if opened is None else text.find("}", opened.end())
    if opened is None or end == -1:
        raise RefusedError("hub.json: no platform object")
    inner, count = PIN.subn(rf'\g<1>"{version}"', text[opened.end() : end], count=1)
    found = text[: opened.end()] + inner + text[end:]
    platform = json.loads(found).get("platform")
    if count != 1 or not isinstance(platform, dict) or platform.get("version") != version:
        raise RefusedError("hub.json: no platform.version to set")
    return found


def _env() -> dict[str, str]:
    """The child's environment: no hub root from the caller, so the cwd names the hub."""
    return {name: value for name, value in os.environ.items() if name != "AGENT_HUB_ROOT"}


def _run(
    command: list[str], cwd: Path, *, codes: frozenset[int] = frozenset({0})
) -> tuple[int, str, str]:
    try:
        done = subprocess.run(  # noqa: S603 - git or the hub CLI, arguments the script built
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
            timeout=CHILD_TIMEOUT,
            env=_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FailedError(f"{shlex.join(command)}: {error}") from None
    out = done.stdout[:MAX_OUTPUT_BYTES].decode(errors="replace")
    err = done.stderr[:MAX_OUTPUT_BYTES].decode(errors="replace")
    if done.returncode not in codes:
        tail = "\n".join((out + err).strip().splitlines()[-20:])
        raise FailedError(f"{shlex.join(command)} exited {done.returncode}: {tail}")
    return done.returncode, out, err


def _git(cwd: Path, *args: str) -> str:
    return _run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd)[1]


def parsed(lines: str, pattern: re.Pattern[str]) -> list[dict[str, str]]:
    """The ``{verb, path}`` of each sync line, ``hub.lock`` aside."""
    found = [pattern.fullmatch(line.strip()) for line in lines.splitlines()]
    return [
        {"verb": match.group(1), "path": match.group(2)}
        for match in found
        if match and match.group(2) != HUB_LOCK
    ]


def sync_list(copy: Path, cli: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    code, out, err = _run(
        [*cli, "sync", "--check"], copy, codes=frozenset({UP_TO_DATE, CONFLICT, PENDING})
    )
    if code == CONFLICT:
        return [], [line for line in (err or out).splitlines() if line.strip()][:MAX_CONFLICTS]
    return parsed(out, WOULD), []


def list_changes(hub: Path, *, repo: Path, version: str, cli: list[str]) -> dict[str, object]:
    _, value, previous = read_hub_json(hub / "hub.json")
    project = value.get("project")
    default = project.get("default_branch") if isinstance(project, dict) else None
    if not isinstance(default, str) or not default:
        raise RefusedError("hub.json: no project.default_branch")
    command = cli or ["uv", "run", "--project", str(repo), "--locked", "--all-packages", "hub"]
    folder = Path(tempfile.mkdtemp(prefix="release-pin-"))
    copy = folder / "hub"
    try:
        _git(hub, "worktree", "add", "-q", "--detach", str(copy), f"origin/{default}")
        try:
            copy_text, _, _ = read_hub_json(copy / "hub.json")
            (copy / "hub.json").write_text(set_pin(copy_text, version), encoding="utf-8")
            files, conflicts = sync_list(copy, command)
        finally:
            _git(hub, "worktree", "remove", "--force", str(copy))
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    lines = [f"{entry['verb']} {entry['path']}" for entry in files[:MAX_FILES]]
    if len(files) > MAX_FILES:
        lines.append(f"and {len(files) - MAX_FILES} more")
    return {
        "from": previous,
        "version": version,
        "count": len(files),
        "files": files[:MAX_FILES],
        "omitted": max(0, len(files) - MAX_FILES),
        "conflicts": conflicts,
        "text": "\n".join(lines) if lines else "none",
    }


def summary_of(*, previous: str, version: str, files: list[dict[str, str]]) -> str:
    head = (
        f"Sets `platform.version` in hub.json from {previous} to {version} (tag v{version})"
        f" and runs `./hub sync`: {len(files)} managed files rewritten."
    )
    lines = [f"- {entry['verb']} `{entry['path']}`" for entry in files]
    body = "\n".join([head, "", "What `hub sync` rewrites:", "", *(lines or ["- none"])])
    return body.encode()[:MAX_SUMMARY].decode(errors="ignore")


def apply_pin(worktree: Path, *, version: str, issue: str, cli: list[str]) -> dict[str, object]:
    if not (worktree / "hub.json").is_file():
        raise RefusedError(f"--worktree: no hub.json in {worktree}")
    text, _, previous = read_hub_json(worktree / "hub.json")
    if _git(worktree, "status", "--porcelain", "--untracked-files=all").strip():
        raise FailedError("the hub worktree is not clean")
    (worktree / "hub.json").write_text(set_pin(text, version), encoding="utf-8")
    command = cli or ["./hub"]
    _, synced, _ = _run([*command, "sync"], worktree)
    _, checked, _ = _run(
        [*command, "sync", "--check"], worktree, codes=frozenset({0, PENDING, CONFLICT})
    )
    if not checked.strip().startswith("up to date"):
        raise FailedError(
            f"./hub sync --check is not up to date after ./hub sync: {checked.strip()[:400]}"
        )
    files = parsed(synced, DONE)
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", f"chore(hub): bump platform to {version} ({issue})")
    return {
        "from": previous,
        "version": version,
        "sha": _git(worktree, "rev-parse", "HEAD").strip(),
        "count": len(files),
        "files": files[:MAX_FILES],
        "summary": summary_of(previous=previous, version=version, files=files),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG)
    actions = parser.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("--repo", required=True)
    applying = actions.add_parser("apply")
    applying.add_argument("--worktree", required=True)
    applying.add_argument("--issue", required=True)
    for action in (listing, applying):
        action.add_argument("--version", required=True)
        # Test only: the CLI to run instead of the platform checkout's (list) or ./hub (apply).
        action.add_argument("--cli", default="", help=argparse.SUPPRESS)
    return parser


def run(given: argparse.Namespace) -> dict[str, object]:
    if not VERSION.fullmatch(given.version):
        raise RefusedError("--version must be X.Y.Z with ASCII digits")
    cli = shlex.split(given.cli)
    if given.action == "list":
        repo = Path(given.repo).resolve()
        return list_changes(Path.cwd().resolve(), repo=repo, version=given.version, cli=cli)
    if not ISSUE.fullmatch(given.issue):
        raise RefusedError("--issue must be <team>-<n>")
    if not given.worktree:
        raise RefusedError("--worktree is empty")
    worktree = Path(given.worktree).resolve()
    return apply_pin(worktree, version=given.version, issue=given.issue, cli=cli)


def main(argv: list[str]) -> int:
    given = _parser().parse_args(argv)
    try:
        found = run(given)
    except RefusedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    except FailedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
