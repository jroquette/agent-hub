# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Print the git evidence of an incident window as one JSON object, read-only.

``evidence.py --since <72h|3d>`` with the report on stdin, run in the hub (the cwd holds
``hub.json``). The report is only checked here: not blank, at most ``MAX_REPORT`` bytes. For each
repo of ``hub.json`` (``../<dir>``), the ref is ``origin/<default branch>`` as last fetched (this
script never fetches): its first-parent commits since the window (merge and squash commits alike),
the files each one changed against its first parent, and the tags created since then.

Output: ``{since, since_iso, repos: [{dir, ref, head, commits: [{sha, at, subject, merge, paths,
more_paths}], more_commits, tags: [{name, sha, at}]}], unreadable: [{repo, reason}], left_out,
trimmed}``. At most ``MAX_REPOS`` repos, ``MAX_COMMITS`` commits, ``MAX_PATHS`` paths a commit
and ``MAX_TAGS`` tags; texts are cut and their control characters dropped; then the paths of
the oldest commits, then the oldest commits, then the oldest tags, then the unreadable entries
go until the JSON fits ``MAX_BYTES`` (``trimmed: true``). A repo that cannot be read is an
``unreadable`` entry, and the others go on. ``left_out`` names what the evidence does not hold
(failing checks on main, logs).

Exit 0 with the JSON; exit 2 on bad input (the report, ``--since``, an unreadable ``hub.json``).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAX_REPORT = 32768
MAX_HUB_JSON = 1024 * 1024
MAX_REPOS = 20
MAX_COMMITS = 100
MAX_PATHS = 50
MAX_TAGS = 20
MAX_SUBJECT = 200
MAX_PATH = 300
MAX_REASON = 300
# The printed JSON and its newline stay within 48 KiB.
MAX_BYTES = 48 * 1024 - 1
MAX_HOURS = 90 * 24
# Not datetime.UTC: the hub's copy also imports on Python 3.9.
UTC = timezone.utc  # noqa: UP017
GIT_TIMEOUT = 60
SINCE = re.compile(r"[1-9][0-9]{0,3}[hd]")
DIR = re.compile(r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*")
SHA = re.compile(r"[0-9a-f]{40}")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
LEFT_OUT = (
    "failing checks on main (GitHub, no token in script nodes)",
    "logs (hub.json declares no log paths)",
)


class BadInputError(Exception):
    """Input this script refuses: exit 2 with its message."""


class UnreadableError(Exception):
    """A repo this script cannot read: an ``unreadable`` entry with its message."""


def clean(text: str, limit: int) -> str:
    return CONTROL.sub("", text)[:limit]


def git(repo: Path, *args: str) -> str:
    """``git <args>`` in ``repo``, its stdout; ``UnreadableError`` when it fails."""
    try:
        done = subprocess.run(  # noqa: S603 - git from PATH, read-only subcommands
            ["git", "-c", "core.quotepath=off", "--no-pager", *args],  # noqa: S607
            cwd=repo,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UnreadableError(f"git {args[0]} failed: {error}") from None
    if done.returncode != 0:
        detail = done.stderr.decode(errors="replace").strip().splitlines()[-1:] or [""]
        raise UnreadableError(f"git {args[0]} failed: {detail[0]}")
    return done.stdout.decode(errors="replace")


def read_report() -> None:
    data = sys.stdin.buffer.read(MAX_REPORT + 1)
    if len(data) > MAX_REPORT:
        rest = len(sys.stdin.buffer.read())
        raise BadInputError(f"report is {len(data) + rest} bytes, over {MAX_REPORT}")
    if not data.decode(errors="replace").strip():
        raise BadInputError("report is blank")


def window(since: str) -> timedelta:
    hours = int(since[:-1]) * (24 if since.endswith("d") else 1) if SINCE.fullmatch(since) else 0
    if not 0 < hours <= MAX_HOURS:
        raise BadInputError("since must look like 72h or 3d (≤ 90d)")
    return timedelta(hours=hours)


def read_hub() -> dict[str, Any]:
    path = Path("hub.json")
    try:
        if not path.is_file() or path.is_symlink():
            raise BadInputError("cannot read hub.json: not a regular file")
        if path.stat().st_size > MAX_HUB_JSON:
            raise BadInputError(f"cannot read hub.json: over {MAX_HUB_JSON} bytes")
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BadInputError(f"cannot read hub.json: {error}") from None
    repos = config.get("repos") if isinstance(config, dict) else None
    if not isinstance(repos, list) or not all(isinstance(repo, dict) for repo in repos):
        raise BadInputError("cannot read hub.json: no 'repos' list of objects")
    read: dict[str, Any] = config
    return read


def changed(repo: Path, sha: str, parents: list[str]) -> list[str]:
    if parents:
        out = git(repo, "diff", "--name-only", "-z", "--no-renames", parents[0], sha)
    else:
        out = git(repo, "show", "--name-only", "-z", "--format=", sha)
    return [name for name in out.split("\0") if name.strip()]


def commits(repo: Path, ref: str, since: str) -> tuple[list[dict[str, Any]], int]:
    total = int(git(repo, "rev-list", "--count", "--first-parent", f"--since={since}", ref))
    fields = "--format=%H%x00%cI%x00%P%x00%s%x1e"
    log = git(repo, "log", "--first-parent", f"--since={since}", f"-n{MAX_COMMITS}", fields, ref)
    found = []
    for record in log.split("\x1e"):
        parts = record.strip("\n").split("\0")
        if len(parts) != 4:
            continue
        sha, at, parents, subject = parts
        if not SHA.fullmatch(sha) or not all(SHA.fullmatch(p) for p in parents.split()):
            continue
        paths = changed(repo, sha, parents.split())
        found.append(
            {
                "sha": sha,
                "at": clean(at, 40),
                "subject": clean(subject, MAX_SUBJECT),
                "merge": len(parents.split()) > 1,
                "paths": [clean(path, MAX_PATH) for path in paths[:MAX_PATHS]],
                "more_paths": max(0, len(paths) - MAX_PATHS),
            }
        )
    return found, max(0, total - len(found))


def tags(repo: Path, since: datetime) -> list[dict[str, str]]:
    fields = (
        "--format=%(refname:short)%00%(*objectname)%00%(objectname)%00%(creatordate:iso-strict)"
    )
    out = git(repo, "for-each-ref", "refs/tags", "--sort=-creatordate", fields)
    found: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\0")
        if len(parts) != 4:
            continue
        name, peeled, sha, at = parts
        try:
            created = datetime.fromisoformat(at)
        except ValueError:
            continue
        sha = peeled or sha
        if created >= since and SHA.fullmatch(sha) and len(found) < MAX_TAGS:
            found.append({"name": clean(name, MAX_SUBJECT), "sha": sha, "at": clean(at, 40)})
    return found


def read_repo(entry: dict[str, Any], default_branch: str, since: datetime) -> dict[str, Any]:
    name = entry.get("dir")
    if not isinstance(name, str) or not DIR.fullmatch(name) or len(name) > 64:
        raise UnreadableError("not a repo dir of hub.json")
    repo = Path("..") / name
    if not repo.is_dir():
        raise UnreadableError(f"not a folder: ../{name}")
    branch = entry.get("default_branch") or default_branch
    ref = f"origin/{branch}"
    try:
        head = git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}").strip()
    except UnreadableError:
        raise UnreadableError(f"no {ref} (fetch it first)") from None
    listed, more = commits(repo, ref, since.isoformat(timespec="seconds"))
    return {
        "dir": name,
        "ref": ref,
        "head": head,
        "commits": listed,
        "more_commits": more,
        "tags": tags(repo, since),
    }


def size(value: dict[str, Any]) -> int:
    return len(json.dumps(value))


def trim(result: dict[str, Any]) -> None:
    """Drop the oldest commits' paths, then the oldest commits, then the oldest tags, then the
    last unreadable entries, until ``result`` fits."""
    total = size(result)
    if total <= MAX_BYTES:
        return
    result["trimmed"] = True
    oldest = sorted(
        (commit for repo in result["repos"] for commit in repo["commits"]),
        key=lambda commit: when(commit["at"]),
    )
    for commit in oldest:
        if total <= MAX_BYTES:
            break
        before = size(commit)
        commit["more_paths"] += len(commit["paths"])
        commit["paths"] = []
        total -= before - size(commit)
    while total > MAX_BYTES and (holder := oldest_holder(result)) is not None:
        dropped = holder["commits"].pop()
        holder["more_commits"] += 1
        # A separator goes with it; an estimate, corrected by the exact size below.
        total -= size(dropped) + len(", ")
        if total <= MAX_BYTES:
            total = size(result)
    while size(result) > MAX_BYTES and (holder := oldest_tag_holder(result)) is not None:
        holder["tags"].pop()
    while size(result) > MAX_BYTES and result["unreadable"]:
        result["unreadable"].pop()


def oldest_tag_holder(result: dict[str, Any]) -> dict[str, Any] | None:
    """The repo whose last (oldest) tag is the oldest of all, or ``None`` when none is left."""
    holders = [repo for repo in result["repos"] if repo["tags"]]
    if not holders:
        return None
    oldest: dict[str, Any] = min(holders, key=lambda repo: when(repo["tags"][-1]["at"]))
    return oldest


def when(at: str) -> datetime:
    try:
        moment = datetime.fromisoformat(at)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def oldest_holder(result: dict[str, Any]) -> dict[str, Any] | None:
    """The repo whose last (oldest) commit is the oldest of all, or ``None`` when none is left."""
    holders = [repo for repo in result["repos"] if repo["commits"]]
    if not holders:
        return None
    oldest: dict[str, Any] = min(holders, key=lambda repo: when(repo["commits"][-1]["at"]))
    return oldest


def evidence(config: dict[str, Any], since: str, delta: timedelta) -> dict[str, Any]:
    start = datetime.now(UTC) - delta
    project = config.get("project")
    default_branch = (project if isinstance(project, dict) else {}).get("default_branch") or "main"
    repos: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    for number, entry in enumerate(config["repos"]):
        label = clean(str(entry.get("dir", "")), MAX_REASON)
        try:
            if number >= MAX_REPOS:
                raise UnreadableError(f"over the {MAX_REPOS}-repo cap")
            repos.append(read_repo(entry, str(default_branch), start))
        except UnreadableError as error:
            if len(unreadable) < MAX_REPOS:
                unreadable.append({"repo": label, "reason": clean(str(error), MAX_REASON)})
    result = {
        "since": since,
        "since_iso": start.isoformat(timespec="seconds"),
        "repos": repos,
        "unreadable": unreadable,
        "left_out": list(LEFT_OUT),
        "trimmed": False,
    }
    trim(result)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="evidence.py")
    parser.add_argument("--since", required=True)
    args = parser.parse_args(argv)
    try:
        delta = window(args.since)
        read_report()
        config = read_hub()
    except BadInputError as error:
        print(f"evidence.py: {error}", file=sys.stderr)
        return 2
    print(json.dumps(evidence(config, args.since, delta)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
