# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Decide whether a PR's diff touches a risky surface; print the answer as one JSON object.

``surface.py --path <clone> --base <sha> --head <sha>`` reads ``git diff -U0 <base> <head>`` in
the clone (hooks, external diffs and text conversions off) into a temporary file, at most
``READ_CAP`` bytes. The security lens runs when this says ``risky``: a script decides it, never
an agent. The six categories are those of the hub's security-reviewer (input handling, auth,
secrets, subprocesses, file paths, parsing). A changed path matches the path rules; an added line
(never a removed one, never one over ``LINE_CHARS`` characters) matches the line rules.

It fails closed: a diff over the cap is ``risky`` and ``truncated``, a git error is ``risky``,
each with a ``reason``. The output: ``{"risky", "categories", "hits", "files", "truncated",
"reason"}``, ``hits`` at most ``HITS_MAX`` ``{"category", "path", "line", "rule"}`` (``line`` null
for a path rule). Commits that are not full shas exit 2.
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
HUNK = re.compile(r"^@@ -[0-9,]+ \+([0-9]+)")
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
            return
        for category, pattern in LINE_RULES:
            for match in pattern.finditer(text):
                self.hit(category, path, line=number, rule=match.group(0))


def classify(diff_text: str, *, cut: bool) -> dict[str, object]:
    """What ``diff_text`` (``git diff -U0``) touches; ``cut`` when it is not the whole diff."""
    finder, path, previous, number = Finder(), "", "", 0
    for line in diff_text.splitlines():
        if line.startswith("--- "):
            previous = line[4:].strip()
        elif line.startswith("+++ "):
            path = path_of(line, previous)
            finder.path(path)
        elif match := HUNK.match(line):
            number = int(match.group(1))
        elif line.startswith("+") and path:
            finder.added(path, number, line[1:])
            number += 1
    categories = [category for category in CATEGORIES if category in finder.categories]
    return {
        "risky": bool(categories) or cut,
        "categories": categories,
        "hits": finder.hits,
        "files": finder.files,
        "truncated": cut,
        "reason": f"the diff is over {READ_CAP} bytes: read as risky" if cut else "",
    }


def closed(reason: str) -> dict[str, object]:
    return {
        "risky": True,
        "categories": [],
        "hits": [],
        "files": 0,
        "truncated": False,
        "reason": reason[:1000],
    }


def surface(path: Path, base: str, head: str) -> dict[str, object]:
    command = [*GIT, "-C", str(path), "diff", "--no-color", "--no-ext-diff", "--no-textconv"]
    with tempfile.TemporaryFile() as output:
        done = subprocess.run(  # noqa: S603 - a git read with fixed arguments, hooks off
            [*command, "-U0", base, head],
            stdout=output,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        if done.returncode != 0:
            return closed("git cannot diff: " + done.stderr.decode(errors="replace").strip())
        output.seek(0)
        data = output.read(READ_CAP + 1)
    cut = len(data) > READ_CAP
    return classify(data[:READ_CAP].decode("utf-8", errors="replace"), cut=cut)


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
