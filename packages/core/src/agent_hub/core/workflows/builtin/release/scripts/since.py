# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""List the PRs merged since the last release tag and propose the version, as JSON.

``since.py --version <X.Y.Z or empty>`` runs in the platform repo's checkout (the node's cwd).
The last tag is the highest ``vX.Y.Z`` tag reachable from ``HEAD``; the PRs are the first-parent
commits after it: a GitHub merge commit (``Merge pull request #N from …``) gives its number and
its body's first line as the title, or the branch tip's subject when the body is empty; any other
commit gives its subject (``… (#N)`` gives the number). A merge whose merged side is already
in the tag (the tagged release PR's own merge commit: the tag is on that PR's head) is no PR.
The bump is ``/release``'s rule: ``!`` or ``BREAKING CHANGE`` → major, any ``feat`` → minor,
``fix`` → patch, else patch; no commit since the tag is ``none``. A given version must be
``X.Y.Z`` (ASCII digits) and greater than the tag.

Prints ``{"last_tag", "previous", "version", "bump", "reason", "count", "prs", "text",
"omitted"}``: ``prs`` holds ``{number, title, type, breaking, sha}`` per commit, oldest first;
``text`` one ``#N title`` line per PR within ``TEXT_BUDGET`` bytes, the rest counted in
``omitted``. Titles are cut to ``MAX_TITLE`` characters, control characters removed. More than
``MAX_COMMITS`` commits, no ``v*`` tag or a bad version exits 2; a git failure exits 1.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import NamedTuple

PROG = "since.py"
MAX_COMMITS = 500
MAX_TITLE = 200
TEXT_BUDGET = 32 * 1024
GIT_TIMEOUT = 120
VERSION = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")
TAG = re.compile(r"v([0-9]+\.[0-9]+\.[0-9]+)")
MERGE = re.compile(r"Merge pull request #([0-9]+) from ")
SQUASHED = re.compile(r"\(#([0-9]+)\)$")
CONVENTIONAL = re.compile(r"([a-z]+)(?:\([^)]*\))?(!)?: ")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Fields and records of one ``git log`` line: unit and record separators.
FIELD, RECORD = "\x1f", "\x1e"


class RefusedError(Exception):
    """Bad input or history: exit 2."""


class GitFailedError(Exception):
    """A git command failed: exit 1."""


class Pr(NamedTuple):
    number: int | None
    title: str
    type: str
    breaking: bool
    sha: str


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
        raise GitFailedError(f"git {args[0]} failed: {error}") from None
    if done.returncode != 0:
        raise GitFailedError(f"git {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def parse(version: str) -> tuple[int, int, int] | None:
    """``X.Y.Z`` (ASCII digits) as numbers, else None."""
    match = VERSION.fullmatch(version)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def last_tag() -> str:
    """The highest ``vX.Y.Z`` tag reachable from HEAD."""
    tags = [tag for tag in _git("tag", "--merged", "HEAD").split() if TAG.fullmatch(tag)]
    if not tags:
        raise RefusedError("no v<X.Y.Z> tag is reachable from HEAD")
    return max(tags, key=lambda tag: parse(tag[1:]) or (0, 0, 0))


def clean(title: str) -> str:
    return CONTROL.sub("", title).strip()[:MAX_TITLE]


def classify(number: int | None, title: str, *, sha: str, body: str = "") -> Pr:
    match = CONVENTIONAL.match(title)
    kind = match.group(1) if match else "other"
    breaking = bool(match and match.group(2)) or "BREAKING CHANGE" in f"{title}\n{body}"
    return Pr(number=number, title=clean(title), type=kind, breaking=breaking, sha=sha)


def _tips(shas: list[str]) -> dict[str, str]:
    """Each commit's subject, in one git call."""
    if not shas:
        return {}
    text = _git("show", "-s", f"--format=%H{FIELD}%s{RECORD}", *shas)
    pairs = (record.strip("\n").split(FIELD, 1) for record in text.split(RECORD) if FIELD in record)
    return {sha: subject for sha, subject in pairs}


def _released(parents: str, tag: str) -> bool:
    """A merge that brings nothing past the tag: the tagged release PR's own merge commit.

    The tag goes on the release PR's head, so that PR's merge commit is not reachable from the
    tag; its merged side (the second parent) is the tagged commit or behind it.
    """
    merged = parents.split()[1:]
    if not merged:
        return False
    try:
        _git("merge-base", "--is-ancestor", merged[-1], f"{tag}^{{commit}}")
    except GitFailedError:
        return False
    return True


def prs_since(tag: str) -> list[Pr]:
    text = _git(
        "log",
        "--first-parent",
        "--reverse",
        f"--format=%H{FIELD}%P{FIELD}%s{FIELD}%b{RECORD}",
        f"{tag}..HEAD",
    )
    records = [
        record.strip("\n").split(FIELD, 3) for record in text.split(RECORD) if FIELD in record
    ]
    records = [record for record in records if not _released(record[1], tag)]
    if len(records) > MAX_COMMITS:
        raise RefusedError(
            f"{len(records)} commits since {tag}, more than {MAX_COMMITS}:"
            " cut a release sooner or pass version"
        )
    # A merge with an empty body: its title is the subject of the PR branch's tip.
    tips = _tips(
        [
            record[1].split()[1]
            for record in records
            if MERGE.match(record[2]) and not record[3].strip() and len(record[1].split()) == 2
        ]
    )
    found: list[Pr] = []
    for sha, parents, subject, body in records:
        merged = MERGE.match(subject)
        if merged is None:
            squashed = SQUASHED.search(subject)
            number = int(squashed.group(1)) if squashed else None
            found.append(classify(number, subject, sha=sha, body=body))
            continue
        first = body.strip().splitlines()[0] if body.strip() else ""
        tip = parents.split()[1] if len(parents.split()) == 2 else ""
        title = first or tips.get(tip, subject)
        found.append(classify(int(merged.group(1)), title, sha=sha, body=body))
    return found


def _named(prs: list[Pr]) -> str:
    return ", ".join(f"#{pr.number}" if pr.number else pr.sha[:12] for pr in prs)


def propose(prs: list[Pr]) -> tuple[str, str]:
    """The bump and its reason, naming the PRs that decide it."""
    if not prs:
        return "none", "no PR merged since the tag"
    breaking = [pr for pr in prs if pr.breaking]
    if breaking:
        return "major", f"major: a breaking change in {_named(breaking)}"
    feats = [pr for pr in prs if pr.type == "feat"]
    if feats:
        return "minor", f"minor: a feat in {_named(feats)}"
    fixes = [pr for pr in prs if pr.type == "fix"]
    if fixes:
        return "patch", f"patch: fixes only, in {_named(fixes)}"
    return "patch", "patch: no feat, fix or breaking change"


def bumped(previous: tuple[int, int, int], bump: str) -> tuple[int, int, int]:
    major, minor, patch = previous
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    if bump == "patch":
        return major, minor, patch + 1
    return previous


def jump(previous: tuple[int, int, int], given: tuple[int, int, int]) -> str:
    if given[0] != previous[0]:
        return "major"
    return "minor" if given[1] != previous[1] else "patch"


def text_of(prs: list[Pr]) -> tuple[str, int]:
    """One ``#N title`` line per PR within the budget; how many did not fit."""
    lines: list[str] = []
    size = 0
    for pr in prs:
        line = f"#{pr.number} {pr.title}" if pr.number else f"{pr.sha[:12]} {pr.title}"
        cost = len(line.encode()) + (1 if lines else 0)
        if size + cost > TEXT_BUDGET:
            break
        lines.append(line)
        size += cost
    return "\n".join(lines), len(prs) - len(lines)


def result(given: str) -> dict[str, object]:
    tag = last_tag()
    previous = parse(tag[1:]) or (0, 0, 0)
    wanted = parse(given) if given else previous
    if wanted is None or (given and wanted <= previous):
        raise RefusedError(f"version {given!r} must be X.Y.Z and greater than {tag}")
    prs = prs_since(tag)
    bump, reason = propose(prs)
    version = bumped(previous, bump)
    if given and prs:
        version, bump = wanted, jump(previous, wanted)
        reason = f"given version {given}; proposed {reason}"
    text, omitted = text_of(prs)
    return {
        "last_tag": tag,
        "previous": tag[1:],
        "version": ".".join(str(part) for part in version),
        "bump": bump,
        "reason": reason,
        "count": len(prs),
        "prs": [pr._asdict() for pr in prs],
        "text": text,
        "omitted": omitted,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--version", required=True)
    given = parser.parse_args(argv)
    try:
        found = result(given.version.strip())
    except RefusedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    except GitFailedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
