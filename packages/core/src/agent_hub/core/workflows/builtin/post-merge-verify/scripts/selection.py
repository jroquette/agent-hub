# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Pick the ACs to verify after a merge (or every week) and print them as one JSON object.

``selection.py --repo <dir> [--sha <sha>] [--ref <ref>]``, run in the hub: ``repo`` is a dir of
``hub.json`` → ``repos``, a sibling of the hub. With a ``sha`` (the merge commit on the default
branch, 7 to 40 hex digits) the mode is ``merge``: the tickets are the ``(KEY-n)`` of the subjects
of ``git log <sha>^1..<sha>`` and the ``KEY-n`` that starts the merged branch's last segment
(``Merge pull request #N from <owner>/<...>/<key>-<n>-...``), and the changed paths are
``git diff --name-only <sha>^1 <sha>``. An AC is selected when its record ties it to a ticket (its
``ticket``, a ``tickets[].key`` whose ``id`` is the ticket, an id ``AC-<n>[.<m>]`` whose ``n`` is
the ticket's number in a record whose ``linear`` names it, a record whose ``linear`` is just the
ticket, or a record folder named after it), else when its verification names a changed path or a
folder holding one. With a blank ``sha`` the mode is ``weekly``: every AC, at ``ref`` (default
``origin/main``, as last fetched). Either way only the ACs of ``repo`` with ``passes: true`` and
not ``withdrawn`` are kept; the others matched count as ``skipped_not_passing``.

The records are the ``features.json`` files under ``brain/features/`` (up to ``MAX_DEPTH`` folders
deep, symlinks not followed, at most ``MAX_RECORDS`` files of ``MAX_RECORD_BYTES`` each). One that
cannot be read is listed in ``unreadable`` (``{path, reason}``) and the others are still read.

Output: ``{"mode", "sha", "repo_path", "tickets", "changed_paths", "paths_truncated", "selected":
[{"feature", "ac", "why"}], "truncated", "skipped_not_passing", "unreadable"}``; ``why`` is
``ticket``, ``path`` or ``weekly``, ``feature`` the record's folder under ``brain/features/``.
Bad input (an unknown repo, a bad or unknown sha or ref, a commit with no parent, git failing)
exits 2 with ``selection.py: <reason>`` on stderr.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

USAGE = "usage: selection.py --repo <dir> [--sha <sha>] [--ref <ref>]"
FEATURES = Path("brain/features")
MAX_DEPTH = 4
MAX_RECORDS = 500
MAX_RECORD_BYTES = 1024 * 1024
MAX_ACS_READ = 20_000
MAX_SELECTED = 2000
MAX_UNREADABLE = 100
MAX_TICKETS = 100
MAX_SUBJECTS = 1000
MAX_PATHS = 5000
MAX_TOKENS = 200
# A tuple, not an except list: ``uv run`` may run this on Python 3.12.
READ_ERRORS = (OSError, ValueError)
REQUIRED = ("id", "repo", "verification", "passes")

SHA = re.compile(r"[0-9a-f]{7,40}")
KEY_IN_SUBJECT = re.compile(r"\(([A-Z][A-Z0-9]*-[0-9]+)\)")
# The merged branch's last segment starts with the ticket's key: ``.../dem-7-short-name``.
MERGED_BRANCH = re.compile(
    r"^Merge pull request #[0-9]+ from \S*/([A-Za-z][A-Za-z0-9]*-[0-9]+)(?:-[^/\s]*)?$"
)
AC_NUMBER = re.compile(r"AC-([0-9]+)(?:\.[0-9]+)?")
AC_ID = re.compile(r"[\x21-\x7e](?:[\x20-\x7e]{0,62}[\x21-\x7e])?")
FEATURE = re.compile(r"[\x20-\x7e]{1,200}")
PATH_TOKEN = re.compile(r"[\w.@-]+(?:/[\w.@-]+)+")


class BadInputError(Exception):
    """The run cannot select: bad input or git failing."""


@dataclass
class Selection:
    tickets: list[str]
    changed: set[str]
    folders: set[str]
    repo: str
    weekly: bool
    selected: list[dict[str, str]] = field(default_factory=list)
    truncated: int = 0
    skipped: int = 0
    unreadable: list[dict[str, str]] = field(default_factory=list)
    read: int = 0

    def unreadable_record(self, path: Path, reason: str) -> None:
        if len(self.unreadable) < MAX_UNREADABLE:
            self.unreadable.append({"path": path.as_posix(), "reason": reason})


def options(argv: list[str]) -> dict[str, str]:
    """``--name value`` pairs; a value may start with ``-`` (it is data, never an option)."""
    names = {"--repo", "--sha", "--ref"}
    if len(argv) % 2:
        raise BadInputError(USAGE)
    found = dict(zip(argv[::2], argv[1::2], strict=True))
    if not set(found) <= names or "--repo" not in found:
        raise BadInputError(USAGE)
    return found


def git(repo: Path, *args: str) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - git with fixed subcommands, read-only
            ["git", "-C", str(repo), *args],  # noqa: S607 - git from PATH
            capture_output=True,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except OSError as error:
        raise BadInputError(f"git failed: {error}") from None
    if done.returncode != 0:
        detail = done.stderr.decode(errors="replace").strip().splitlines()
        raise BadInputError(f"git {args[0]} failed: {detail[-1] if detail else done.returncode}")
    return done.stdout.decode(errors="replace")


def repo_path(name: str) -> Path:
    try:
        config = json.loads(Path("hub.json").read_text(encoding="utf-8"))
    except READ_ERRORS as error:
        raise BadInputError(f"cannot read hub.json: {type(error).__name__}") from None
    repos = config.get("repos") if isinstance(config, dict) else None
    dirs = [item.get("dir") for item in repos or [] if isinstance(item, dict)]
    if name not in dirs:
        raise BadInputError(f"{name!r} is not a repo of hub.json")
    path = (Path.cwd().parent / name).resolve()
    if not path.is_dir():
        raise BadInputError(f"the repo {name!r} is not checked out at {path}")
    return path


def commit(repo: Path, given: str) -> str:
    """The full sha of ``given`` (a sha or a ref), a commit of ``repo``."""
    if given.startswith("-"):
        raise BadInputError(f"not a commit: {given!r}")
    try:
        return git(repo, "rev-parse", "--verify", "--quiet", f"{given}^{{commit}}").strip()
    except BadInputError:
        raise BadInputError(f"unknown commit: {given!r}") from None


def tickets_of(subjects: list[str]) -> list[str]:
    found: list[str] = []
    for subject in subjects:
        keys = KEY_IN_SUBJECT.findall(subject)
        if merged := MERGED_BRANCH.match(subject):
            keys.append(merged.group(1).upper())
        found.extend(key for key in keys if key not in found)
    return found[:MAX_TICKETS]


def merge_facts(repo: Path, sha: str) -> tuple[list[str], list[str]]:
    """The merge's tickets and changed paths (``sha`` against its first parent)."""
    try:
        parent = git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^1").strip()
    except BadInputError:
        raise BadInputError(f"the commit {sha[:12]} has no parent") from None
    log = git(repo, "log", f"--max-count={MAX_SUBJECTS}", "--format=%s", f"{parent}..{sha}")
    diff = git(repo, "diff", "--name-only", "--no-renames", "-z", parent, sha)
    return tickets_of(log.splitlines()), [path for path in diff.split("\0") if path]


def folders_of(paths: list[str]) -> set[str]:
    folders: set[str] = set()
    for path in paths:
        parts = path.split("/")
        folders.update("/".join(parts[:end]) for end in range(1, len(parts)))
    return folders


def records(root: Path) -> Iterator[Path]:
    """The ``features.json`` files under ``root``, depth first in name order, links skipped."""
    pending = [(root, 0)]
    while pending:
        folder, depth = pending.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda entry: entry.name, reverse=True)
        except OSError:
            continue
        children = []
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.name == "features.json" and entry.is_file():
                yield Path(entry.path)
            elif entry.is_dir() and depth < MAX_DEPTH:
                children.append((Path(entry.path), depth + 1))
        pending.extend(children)


def read_record(path: Path) -> dict[str, object] | str:
    """The record, or why it cannot be read."""
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            return "too large"
        data = json.loads(path.read_text(encoding="utf-8"))
    except READ_ERRORS:
        return "not JSON"
    if not isinstance(data, dict) or not isinstance(data.get("acs"), list):
        return "no acs list"
    return data


def keys_of(record: dict[str, object]) -> tuple[set[str], dict[str, str]]:
    """The record's ``linear`` keys and its ``tickets[].key`` → ``id`` map."""
    linear = record.get("linear")
    keys = {linear} if isinstance(linear, str) else set()
    if isinstance(linear, list):
        keys = {item for item in linear if isinstance(item, str)}
    tickets = record.get("tickets")
    aliases = {
        str(item["key"]): str(item["id"])
        for item in (tickets if isinstance(tickets, list) else [])
        if isinstance(item, dict) and "key" in item and "id" in item
    }
    return keys, aliases


def ticket_of(ac: dict[str, object], key: str, *, record: dict[str, object], folder: str) -> bool:
    """Whether ``ac`` belongs to the ticket ``key`` by one of the records' ID schemes."""
    linear, aliases = keys_of(record)
    ticket = ac.get("ticket")
    number = AC_NUMBER.fullmatch(str(ac["id"]))
    return (
        ticket == key
        or (isinstance(ticket, str) and aliases.get(ticket) == key)
        or (number is not None and key in linear and key.rsplit("-", 1)[1] == number.group(1))
        or linear == {key}
        or folder.rsplit("/", 1)[-1].upper() == key
    )


def why(ac: dict[str, object], *, record: dict[str, object], folder: str, run: Selection) -> str:
    """Why ``ac`` is selected (blank: it is not)."""
    if run.weekly:
        return "weekly"
    if any(ticket_of(ac, key, record=record, folder=folder) for key in run.tickets):
        return "ticket"
    tokens = PATH_TOKEN.findall(str(ac["verification"]))[:MAX_TOKENS]
    if any(token in run.changed or token in run.folders for token in tokens):
        return "path"
    return ""


def problem(ac: object, index: int) -> str:
    """Why the record's AC ``index`` cannot be read (blank: it can)."""
    if not isinstance(ac, dict):
        return f"AC {index} is not an object"
    lacking = [key for key in REQUIRED if key not in ac]
    if lacking:
        return f"AC {index} lacks {lacking[0]}"
    if not isinstance(ac["id"], str) or not AC_ID.fullmatch(ac["id"]):
        return f"AC {index} id is not printable ASCII of 1 to 64 characters"
    return ""


def take(path: Path, record: dict[str, object], *, acs: list[object], run: Selection) -> None:
    folder = path.parent.relative_to(FEATURES).as_posix()
    for index, ac in enumerate(acs):
        if run.read >= MAX_ACS_READ:
            run.unreadable_record(path, "AC read cap reached")
            return
        run.read += 1
        if reason := problem(ac, index):
            run.unreadable_record(path, reason)
            continue
        if not isinstance(ac, dict) or ac["repo"] != run.repo:
            continue
        if not (reason := why(ac, record=record, folder=folder, run=run)):
            continue
        if ac["passes"] is not True or ac.get("withdrawn"):
            run.skipped += 1
        elif len(run.selected) < MAX_SELECTED:
            run.selected.append({"feature": folder, "ac": str(ac["id"]), "why": reason})
        else:
            run.truncated += 1


def select(run: Selection) -> None:
    for count, path in enumerate(records(FEATURES)):
        if count >= MAX_RECORDS:
            run.unreadable_record(FEATURES, f"more than {MAX_RECORDS} records")
            return
        record = read_record(path)
        acs = record.get("acs") if isinstance(record, dict) else None
        if isinstance(record, str):
            run.unreadable_record(path, record)
        elif not FEATURE.fullmatch(path.parent.relative_to(FEATURES).as_posix()):
            run.unreadable_record(path, "the folder is not printable ASCII of 1 to 200 characters")
        elif isinstance(acs, list):
            take(path, record, acs=acs, run=run)


def selection(given: dict[str, str]) -> dict[str, object]:
    repo = repo_path(given["--repo"])
    sha = given.get("--sha", "")
    if sha and not SHA.fullmatch(sha):
        raise BadInputError(f"not a commit sha: {sha!r}")
    full = commit(repo, sha or given.get("--ref", "origin/main"))
    tickets, paths = merge_facts(repo, full) if sha else ([], [])
    run = Selection(
        tickets=tickets,
        changed=set(paths[:MAX_PATHS]),
        folders=folders_of(paths[:MAX_PATHS]),
        repo=given["--repo"],
        weekly=not sha,
    )
    select(run)
    return {
        "mode": "merge" if sha else "weekly",
        "sha": full,
        "repo_path": str(repo),
        "tickets": tickets,
        "changed_paths": min(len(paths), MAX_PATHS),
        "paths_truncated": len(paths) > MAX_PATHS,
        "selected": run.selected,
        "truncated": run.truncated,
        "skipped_not_passing": run.skipped,
        "unreadable": run.unreadable,
    }


def main(argv: list[str]) -> int:
    try:
        result = selection(options(argv))
    except BadInputError as error:
        print(f"selection.py: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
