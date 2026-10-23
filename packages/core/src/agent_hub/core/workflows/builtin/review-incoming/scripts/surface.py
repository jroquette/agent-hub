# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Decide whether a PR's diff touches a risky surface; print the answer as one JSON object.

``surface.py --path <clone> --base <sha> --head <sha>`` reads ``git diff -U0 <base> <head>`` in the
clone (hooks, external diffs, text conversions and rename detection off) into a temporary file, at
most ``READ_CAP`` bytes, and the changed paths from ``git diff --name-only``, so a binary, renamed
or mode-only file meets the path rules too. The security lens runs when this says ``risky``: a
script decides it, never an agent. The six categories are those of the hub's security-reviewer
(input handling, auth, secrets, subprocesses, file paths, parsing). A changed path matches the path
rules; an added line (never a removed one) matches the line rules. ``---`` and ``+++`` are file
headers only between a ``diff --git`` line and the file's first hunk, so an added line that starts
with ``++`` is read as one; an added line over ``LINE_CHARS`` characters is not read but counted as
a hit (``unread``), so it makes the diff ``risky``.

It fails closed: a diff over the cap is ``risky`` and ``truncated``, a git error is ``risky``, each
with a ``reason``. The output: ``{"risky", "categories", "hits", "files", "truncated", "reason"}``,
``hits`` at most ``HITS_MAX`` ``{"category", "path", "line", "rule"}`` (``line`` null for a path
rule). Commits that are not full shas exit 2.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

READ_CAP = 8 * 1024 * 1024
LINE_CHARS = 2000
HITS_MAX = 50
PATH_CHARS = 160
SHA = re.compile(r"[0-9a-f]{40}")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f`]")
UNREAD = f"line over {LINE_CHARS} characters"
HUNK = re.compile(r"^@{2} -[0-9,]+ \+([0-9]+)")
CATEGORIES = ("input handling", "auth", "secrets", "subprocesses", "file paths", "parsing")
PATH_RULES = (
    ("auth", re.compile(r"auth|login|session|permission|acl|oauth|jwt|csrf|cors")),
    ("secrets", re.compile(r"secret|credential|password|token|\.env|crypto")),
    ("input handling", re.compile(r"upload|sanitiz|validat")),
    ("parsing", re.compile(r"parse|parser|serializ")),
    ("subprocesses", re.compile(r"subprocess|shell|exec|^\.github/workflows/")),
)
LINE_RULES = (
    (
        "subprocesses",
        re.compile(
            r"subprocess|Popen|os\.system|shell=True|child_process|spawn\(|(?<![A-Za-z_])exec\(|"
            r"(?<![A-Za-z_])eval\("
        ),
    ),
    (
        "file paths",
        re.compile(r"(?<![A-Za-z_])open\(|Path\(|os\.path\.join|\.\./|sendFile|readFile"),
    ),
    (
        "parsing",
        re.compile(r"pickle|yaml\.load\(|json\.loads|JSON\.parse|xml|fromstring|unmarshal"),
    ),
    (
        "input handling",
        re.compile(
            r"request\.|req\.(?:body|query|params)|argv|(?<![A-Za-z_])input\(|FormData|"
            r"dangerouslySetInnerHTML|innerHTML"
        ),
    ),
    ("auth", re.compile(r"authorize|permission|is_admin|login|jwt|session", re.IGNORECASE)),
    (
        "secrets",
        re.compile(r"secret|token|api_key|password|getenv|environ|private key", re.IGNORECASE),
    ),
)
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.quotePath=false")


def shown(path: str) -> str:
    return CONTROL.sub("", path)[:PATH_CHARS]


def path_of(line: str, previous: str) -> str:
    """The changed file a ``+++`` line names: the old one (``---``) for a deleted file."""
    name = line[4:].strip()
    if name == "/dev/null":
        name = previous
    name = name.strip('"')
    return name[2:] if name[:2] in {"a/", "b/"} else name


class Finder:
    """The categories and the first hits of one diff."""

    def __init__(self) -> None:
        self.categories: set[str] = set()
        self.hits: list[dict[str, object]] = []
        self.files = 0
        self.unread = False

    def hit(self, category: str, path: str, *, line: int | None, rule: str) -> None:
        self.categories.add(category)
        if len(self.hits) < HITS_MAX:
            self.hits.append(
                {"category": category, "path": shown(path), "line": line, "rule": rule}
            )

    def path(self, path: str) -> None:
        self.files += 1
        for category, pattern in PATH_RULES:
            match = pattern.search(path.lower())
            if match:
                self.hit(category, path, line=None, rule=match.group(0))

    def added(self, path: str, number: int, text: str) -> None:
        if len(text) > LINE_CHARS:
            self.unread = True
            self.hits.append(
                {"category": "unread", "path": shown(path), "line": number, "rule": UNREAD}
            )
            return
        for category, pattern in LINE_RULES:
            for match in pattern.finditer(text):
                self.hit(category, path, line=number, rule=match.group(0))


def classify(diff_text: str, *, cut: bool, paths: list[str] | None = None) -> dict[str, object]:
    """What ``diff_text`` (``git diff -U0``) touches; ``cut`` when it is not the whole diff.
    ``paths`` (``git diff --name-only``) are the changed files the path rules read: a binary,
    renamed or mode-only file has no ``+++`` line. Without them, the ``+++`` lines are read."""
    finder = Finder()
    for name in paths or []:
        finder.path(name)
    read_lines(finder, diff_text, headers=paths is None)
    categories = [category for category in CATEGORIES if category in finder.categories]
    reasons = [f"the diff is over {READ_CAP} bytes: read as risky"] if cut else []
    if finder.unread:
        reasons.append(f"an added line is over {LINE_CHARS} characters: read as risky")
    return {
        "risky": bool(categories) or cut or finder.unread,
        "categories": categories,
        "hits": finder.hits[:HITS_MAX],
        "files": finder.files,
        "truncated": cut,
        "reason": "; ".join(reasons),
    }


def read_lines(finder: Finder, diff_text: str, *, headers: bool) -> None:
    """The added lines through the line rules; with ``headers``, the ``+++`` paths too."""
    path, previous, number, header = "", "", 0, False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            # A content line always starts with "+", "-", " " or "\\": this is a new file.
            header, path, previous = True, "", ""
        elif header and line.startswith("--- "):
            previous = line[4:].strip()
        elif header and line.startswith("+++ "):
            path = path_of(line, previous)
            if headers:
                finder.path(path)
        elif match := HUNK.match(line):
            header, number = False, int(match.group(1))
        elif not header and line.startswith("+") and path:
            finder.added(path, number, line[1:])
            number += 1


def closed(reason: str) -> dict[str, object]:
    return {
        "risky": True,
        "categories": [],
        "hits": [],
        "files": 0,
        "truncated": False,
        "reason": reason[:1000],
    }


def git_diff(path: Path, *args: str) -> tuple[bytes, bool] | str:
    """``git diff <args>`` in the clone, renames off: its first ``READ_CAP`` bytes and whether
    it was cut, or git's error."""
    command = [*GIT, "-C", str(path), "diff", "--no-color", "--no-ext-diff", "--no-textconv"]
    with tempfile.TemporaryFile() as output:
        done = subprocess.run(  # noqa: S603 - a git read with fixed arguments, hooks off
            [*command, "--no-renames", *args],
            stdout=output,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        if done.returncode != 0:
            return "git cannot diff: " + done.stderr.decode(errors="replace").strip()
        output.seek(0)
        data = output.read(READ_CAP + 1)
    return data[:READ_CAP], len(data) > READ_CAP


def surface(path: Path, base: str, head: str) -> dict[str, object]:
    names = git_diff(path, "--name-only", "-z", base, head)
    patch = git_diff(path, "-U0", base, head)
    if isinstance(names, str):
        return closed(names)
    if isinstance(patch, str):
        return closed(patch)
    paths = [name for name in names[0].decode("utf-8", errors="replace").split("\0") if name]
    text = patch[0].decode("utf-8", errors="replace")
    return classify(text, cut=names[1] or patch[1], paths=paths)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="surface.py")
    for name in ("--path", "--base", "--head"):
        parser.add_argument(name, required=True)
    given = parser.parse_args(argv)
    if not (SHA.fullmatch(given.base) and SHA.fullmatch(given.head)):
        print("surface.py: base and head must be full commit shas", file=sys.stderr)
        return 2
    print(json.dumps(surface(Path(given.path), given.base, given.head), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
