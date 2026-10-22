# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The doc lines at the base that still name a changed contract name, as JSON.

``mentions.py`` reads ``contract.py``'s output on stdin (``repo_path``, ``base``, ``names``) and
reads the repo's docs at ``base`` with git (``git ls-tree``, ``git grep``, ``git show``: never the
working tree, so the line numbers are the ones a branch from ``base`` holds). A mention is a line
where a name appears as a whole token inside an inline code span or a fenced code block; a
``path`` name also counts as the full path or its basename (8 characters or more, with a dot)
anywhere on the line.

Which docs: ``docs/**/*.md``, the root ``README.md``, ``AGENTS.md``, ``CLAUDE.md`` and
``CONTRIBUTING.md``, and any ``AGENTS.md`` or ``README.md`` in a subfolder may be fixed; never a
``CHANGELOG``, a hidden or ``node_modules`` path, or a file that is not ``.md``. An ADR file (a
``.md`` under a folder named ``adr``, ``adrs`` or ``decisions``) is read but never offered for a
fix, whatever its status: its lines are listed apart with the ADR's status word.

Prints ``{"fixable_count", "fixable": [{"path", "line", "text", "names"}], "adr": [{"path",
"line", "text", "names", "status"}], "notes": [{"path", "reason"}], "truncated"}``: files not
read (larger than 1 MiB, not UTF-8, the read budget spent) and lines too long to fix go to
``notes``; mentions past the prompt budget are counted in ``truncated``. Bad input on stdin exits
2; a git failure exits 1. Both say why on stderr.
"""

import json
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import NamedTuple

PROG = "mentions.py"
MAX_STDIN = 1024 * 1024
MAX_FILES = 2000
MAX_FILE_BYTES = 1024 * 1024
MAX_READ_BYTES = 64 * 1024 * 1024
MAX_LINE = 2000
MAX_FIXABLE_BYTES = 96 * 1024
MAX_ADR = 50
MAX_ADR_TEXT = 500
MAX_NOTES = 50
GIT_TIMEOUT = 120
MIN_BASENAME = 8
HEAD_LINES = 40
ROOT_DOCS = frozenset({"README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md"})
NESTED_DOCS = frozenset({"README.md", "AGENTS.md"})
ADR_FOLDERS = frozenset({"adr", "adrs", "decisions"})
ACCEPTED = frozenset({"accepted", "superseded"})
STATUS_LINE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?status(?:\*\*)?\s*:\s*(?:\*\*)?\s*([A-Za-z]+)", re.IGNORECASE
)
STATUS_HEADING = re.compile(r"^#{1,6}\s*status\s*$", re.IGNORECASE)
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
TICKS = re.compile(r"`+")
WORD_CHARS = "A-Za-z0-9_-"


class Mention(NamedTuple):
    path: str
    line: int
    text: str
    names: list[str]


# The doc rules below are the same in doc_fix.py (a parity test holds them equal): a pack
# script cannot import another.
def doc_role(path: str) -> str | None:
    """``edit`` for a doc a fix may change, ``adr`` for an ADR file (read, never changed)."""
    parts = path.split("/")
    base = parts[-1]
    if any(part.startswith(".") or part in {"", "node_modules"} for part in parts):
        return None
    if not base.endswith(".md") or base.upper().startswith("CHANGELOG"):
        return None
    if ADR_FOLDERS.intersection(parts[:-1]):
        return "adr"
    if parts[0] == "docs" or (len(parts) == 1 and base in ROOT_DOCS) or base in NESTED_DOCS:
        return "edit"
    return None


def adr_status(head: str) -> str:
    """The ADR's status word, lowercased: the first ``Status:`` line, or the word after a
    ``## Status`` heading, in the first 40 lines; empty when there is none."""
    lines = head.splitlines()[:HEAD_LINES]
    for index, line in enumerate(lines):
        if found := STATUS_LINE.match(line):
            return found.group(1).lower()
        if STATUS_HEADING.match(line):
            following = [text.strip() for text in lines[index + 1 :] if text.strip()]
            word = re.match(r"[A-Za-z]+", following[0]) if following else None
            return word.group(0).lower() if word else ""
    return ""


def is_accepted(status: str) -> bool:
    """An accepted (or superseded) ADR: its wording is history, reported and never edited."""
    return status in ACCEPTED


def _code_spans(line: str) -> list[str]:
    """The text of each inline code span on a line outside a fence."""
    spans: list[str] = []
    position = 0
    while opening := TICKS.search(line, position):
        width = len(opening.group(0))
        closing = next(
            (tick for tick in TICKS.finditer(line, opening.end()) if len(tick.group(0)) == width),
            None,
        )
        if closing is None:
            break
        spans.append(line[opening.end() : closing.start()])
        position = closing.end()
    return spans


def _code_lines(text: str) -> Iterator[tuple[int, str, list[str]]]:
    """Each line (1-based) with the code it holds: all of it inside a fence, else its spans."""
    fence = ""
    for number, line in enumerate(text.splitlines(), start=1):
        marker = FENCE.match(line)
        if fence:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = ""
            else:
                yield number, line, [line]
        elif marker:
            fence = marker.group(1)
        else:
            yield number, line, _code_spans(line)


def _has_token(name: str, text: str) -> bool:
    pattern = rf"(?<![{WORD_CHARS}]){re.escape(name)}(?![{WORD_CHARS}])"
    return re.search(pattern, text) is not None


def _named(name: dict[str, object], line: str, code: list[str]) -> bool:
    text = str(name.get("name", ""))
    if any(_has_token(text, part) for part in code):
        return True
    if name.get("kind") != "path":
        return False
    basename = text.rsplit("/", 1)[-1]
    long_enough = len(basename) >= MIN_BASENAME and "." in basename
    return _has_token(text, line) or (long_enough and _has_token(basename, line))


def mentions_in(text: str, names: Sequence[dict[str, object]]) -> list[tuple[int, list[str]]]:
    """The lines of ``text`` that name one of ``names``, with the names each holds."""
    found: list[tuple[int, list[str]]] = []
    for number, line, code in _code_lines(text):
        held = [str(name["name"]) for name in names if _named(name, line, code)]
        if held:
            found.append((number, held))
    return found


class InputError(Exception):
    """Bad input: exit 2."""


class GitFailedError(Exception):
    """A git command failed: exit 1."""


def _git(repo: Path, *args: str, accept: tuple[int, ...] = (0,)) -> bytes:
    command = ["git", "-c", "core.quotePath=false", *args]
    try:
        done = subprocess.run(  # noqa: S603 - git from PATH, arguments the script built
            command, cwd=repo, capture_output=True, check=False, timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitFailedError(f"git {args[0]}: {error}") from None
    if done.returncode not in accept:
        reason = done.stderr.decode("utf-8", errors="replace").strip()
        raise GitFailedError(f"git {' '.join(args[:2])}: {reason}")
    return done.stdout


def _contract() -> tuple[Path, str, list[dict[str, object]]]:
    text = sys.stdin.read(MAX_STDIN + 1)
    if len(text) > MAX_STDIN:
        raise InputError("stdin: larger than 1 MiB")
    try:
        value = json.loads(text)
    except ValueError as error:
        raise InputError(f"stdin: {error}") from None
    if not isinstance(value, dict):
        raise InputError("stdin: not a JSON object")
    repo, base, names = value.get("repo_path"), value.get("base"), value.get("names")
    if not isinstance(repo, str) or not isinstance(base, str) or not isinstance(names, list):
        raise InputError("stdin: repo_path, base and names are needed")
    kept = [name for name in names if isinstance(name, dict) and isinstance(name.get("name"), str)]
    return Path(repo), base, kept


def _patterns(names: list[dict[str, object]]) -> list[str]:
    patterns: list[str] = []
    for name in names:
        text = str(name["name"])
        patterns += ["-e", text]
        basename = text.rsplit("/", 1)[-1]
        if name.get("kind") == "path" and basename != text:
            patterns += ["-e", basename]
    return patterns


def candidates(repo: Path, base: str, names: list[dict[str, object]]) -> list[tuple[str, str]]:
    """The docs at ``base`` holding a name's text, with their role, at most ``MAX_FILES``."""
    if not names:
        return []
    out = _git(repo, "grep", "-l", "-I", "-F", "-z", *_patterns(names), base, accept=(0, 1))
    paths = [
        item.decode("utf-8", errors="replace").removeprefix(f"{base}:") for item in out.split(b"\0")
    ]
    roles = [(path, doc_role(path)) for path in sorted(set(paths)) if path]
    return [(path, role) for path, role in roles if role is not None][:MAX_FILES]


class Scan:
    """The output under construction, within its bounds."""

    def __init__(self) -> None:
        self.fixable: list[dict[str, object]] = []
        self.adr: list[dict[str, object]] = []
        self.notes: list[dict[str, object]] = []
        self.truncated = 0
        self.size = 2
        self.read = 0

    def note(self, path: str, reason: str) -> None:
        if len(self.notes) < MAX_NOTES:
            self.notes.append({"path": path, "reason": reason})
        else:
            self.truncated += 1

    def add_fix(self, mention: Mention) -> None:
        if len(mention.text) > MAX_LINE:
            self.note(mention.path, f"line {mention.line} longer than {MAX_LINE} characters")
            return
        entry = mention._asdict()
        self.size += len(json.dumps(entry).encode()) + 2
        if self.size > MAX_FIXABLE_BYTES:
            self.truncated += 1
        else:
            self.fixable.append(entry)

    def add_adr(self, mention: Mention, status: str) -> None:
        if len(self.adr) >= MAX_ADR:
            self.truncated += 1
            return
        entry = mention._asdict() | {"text": mention.text[:MAX_ADR_TEXT], "status": status}
        self.adr.append(entry)

    def output(self) -> dict[str, object]:
        return {
            "fixable_count": len(self.fixable),
            "fixable": self.fixable,
            "adr": self.adr,
            "notes": self.notes,
            "truncated": self.truncated,
        }


def _text(repo: Path, base: str, *, path: str, scan: Scan) -> str | None:
    """The doc's text at ``base``, or ``None`` with a note when it is not read."""
    size = int(_git(repo, "cat-file", "-s", f"{base}:{path}").strip() or b"0")
    if size > MAX_FILE_BYTES:
        scan.note(path, "larger than 1 MiB")
        return None
    if scan.read + size > MAX_READ_BYTES:
        scan.note(path, "read budget spent")
        return None
    scan.read += size
    try:
        return _git(repo, "show", f"{base}:{path}").decode("utf-8")
    except UnicodeDecodeError:
        scan.note(path, "not UTF-8")
        return None


def scan_docs(repo: Path, base: str, names: list[dict[str, object]]) -> dict[str, object]:
    scan = Scan()
    for path, role in candidates(repo, base, names):
        text = _text(repo, base, path=path, scan=scan)
        if text is None:
            continue
        lines = text.splitlines()
        status = adr_status(text) if role == "adr" else ""
        for number, held in mentions_in(text, names):
            mention = Mention(path, number, lines[number - 1], held)
            if role == "adr":
                scan.add_adr(mention, status)
            else:
                scan.add_fix(mention)
    return scan.output()


def main(argv: list[str]) -> int:
    if argv:
        print(f"{PROG}: takes no arguments (the contract comes on stdin)", file=sys.stderr)
        return 2
    try:
        repo, base, names = _contract()
        found = scan_docs(repo, base, names)
    except InputError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    except GitFailedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
