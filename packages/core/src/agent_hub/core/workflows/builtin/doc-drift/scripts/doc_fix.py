# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Check the judge's doc lines, then write and commit the approved ones, as JSON.

``doc_fix.py plan --repo-path <p> --base <sha> --names <json> --adr <json> --notes <json>
--names-truncated <n> --patch-truncated <bool> --mentions-truncated <n>`` reads the judge's reply
on stdin (empty when the judge was skipped). A fix is kept only when its path is a doc this run
may change (never an ADR, a ``CHANGELOG``, a hidden path or a non-``.md`` file), the line at
``base`` equals its ``old`` text, ``old`` names a changed name as a whole token, ``new`` is one
different line of at most 1000 characters, and no earlier fix targets the same line. A fix aimed
at an ADR line joins the ADR lines ``mentions.py`` found: never edited, they are listed as
superseded wording (an accepted ADR) or as wording to change by hand (any other status). Prints
``{"verdict": "clean" | "reported" | "proposed", "fixes", "items": [{"n", "path", "line", "old",
"new", "reason"}], "superseded", "refused": [{"path", "line", "reason"}], "notes", "message"}``;
``message`` is the approval gate's text (at most 64 KiB: items past it are refused).

``doc_fix.py apply --worktree <p> --base <sha> --label <text> --subject-prefix <text> --note
<text>`` reads ``plan``'s output on stdin, in the run's worktree (its HEAD at ``base``). It
re-checks each item, replaces the line (keeping the file's line endings), commits the changed
docs with hooks off as ``<prefix>fix doc lines stale after <label>``, then checks the commit:
every changed path is a planned doc with as many lines added as removed as planned, and nothing
else is changed. A resumed run finds its commit and checks it again. Prints ``{"changes",
"files", "skipped": [{"path", "line", "reason"}], "summary"}``; ``summary`` (at most 8000
characters) is the PR's text, with the owner's note fenced.

Bad input exits 2; a git failure, or a commit that holds anything but the planned lines, exits 1.
Both say why on stderr.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

PROG = "doc_fix.py"
MAX_STDIN = 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_LINE = 1000
MAX_ITEMS = 60
MAX_SUPERSEDED = 50
MAX_REFUSED = 200
# Byte budgets that keep plan's output within a script's 512 KiB of stdout.
MAX_LIST_BYTES = 64 * 1024
MAX_NOTES_BYTES = 32 * 1024
MAX_MESSAGE = 64 * 1024
MESSAGE_RESERVE = 16 * 1024
MAX_SUMMARY = 8000
MAX_NOTE = 2000
MAX_SHOWN = 300
GIT_TIMEOUT = 120
HEAD_LINES = 40
MIN_BASENAME = 8
WORD_CHARS = "A-Za-z0-9_-"
ROOT_DOCS = frozenset({"README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md"})
NESTED_DOCS = frozenset({"README.md", "AGENTS.md"})
ADR_FOLDERS = frozenset({"adr", "adrs", "decisions"})
ACCEPTED = frozenset({"accepted", "superseded"})
STATUS_LINE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?status(?:\*\*)?\s*:\s*(?:\*\*)?\s*([A-Za-z]+)", re.IGNORECASE
)
STATUS_HEADING = re.compile(r"^#{1,6}\s*status\s*$", re.IGNORECASE)
TICKS = re.compile(r"`+")
REGENERATE = re.compile(r"^([A-Za-z0-9_.-]*llms[A-Za-z0-9_.-]*)\s*:(?!=)", re.MULTILINE)
NOT_ALLOWED = "not a doc this run may change"
# Tuples, not bare lists in the except clauses: a seeded script still parses as Python 3.9.
READ_ERRORS = (OSError, UnicodeDecodeError)
SHOW_ERRORS = (OSError, subprocess.SubprocessError, UnicodeDecodeError)


# The doc rules below are the same in mentions.py (a parity test holds them equal): a pack
# script cannot import another.
def doc_lines(text: str) -> list[str]:
    """A doc's lines as git numbers them: split on ``\\n`` only, a final ``\\r`` dropped."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


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
    lines = doc_lines(head)[:HEAD_LINES]
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


class InputError(Exception):
    """Bad input: exit 2."""


class GitFailedError(Exception):
    """A git command failed, or the commit holds more than the plan: exit 1."""


def _git(folder: Path, *args: str, accept: tuple[int, ...] = (0,)) -> str:
    command = ["git", "-c", "core.quotePath=false", "-c", "core.hooksPath=/dev/null", *args]
    try:
        done = subprocess.run(  # noqa: S603 - git from PATH, arguments the script built
            command, cwd=folder, capture_output=True, check=False, timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitFailedError(f"git {args[0]}: {error}") from None
    if done.returncode not in accept:
        reason = done.stderr.decode("utf-8", errors="replace").strip()
        raise GitFailedError(f"git {' '.join(args[:2])}: {reason}")
    return done.stdout.decode("utf-8", errors="replace")


def _stdin() -> str:
    text = sys.stdin.read(MAX_STDIN + 1)
    if len(text) > MAX_STDIN:
        raise InputError("stdin: larger than 1 MiB")
    return text


def _json_list(text: str, what: str) -> list[dict[str, object]]:
    """A JSON array argument (empty text, from a skipped node, is an empty list)."""
    if not text.strip():
        return []
    try:
        value = json.loads(text)
    except ValueError as error:
        raise InputError(f"{what}: {error}") from None
    if not isinstance(value, list):
        raise InputError(f"{what}: not a JSON array")
    return [item for item in value if isinstance(item, dict)]


def _count(text: str, what: str) -> int:
    if not text.strip():
        return 0
    try:
        return max(0, int(text))
    except ValueError:
        raise InputError(f"{what}: not a number") from None


def _has_token(name: str, text: str) -> bool:
    pattern = rf"(?<![{WORD_CHARS}]){re.escape(name)}(?![{WORD_CHARS}])"
    return re.search(pattern, text) is not None


def names_a_change(line: str, names: list[dict[str, object]]) -> bool:
    """Whether ``line`` names a changed name as a whole token (a path also by its basename)."""
    for name in names:
        text = str(name.get("name", ""))
        basename = text.rsplit("/", 1)[-1]
        by_basename = name.get("kind") == "path" and len(basename) >= MIN_BASENAME
        if (text and _has_token(text, line)) or (by_basename and _has_token(basename, line)):
            return True
    return False


class BaseDocs:
    """The repo's docs at the base commit, read once each."""

    def __init__(self, repo: Path, base: str) -> None:
        self.repo, self.base = repo, base
        self.texts: dict[str, str | None] = {}

    def text(self, path: str) -> str | None:
        if path not in self.texts:
            self.texts[path] = self._read(path)
        return self.texts[path]

    def _read(self, path: str) -> str | None:
        where = f"{self.base}:{path}"
        size = _git(self.repo, "cat-file", "-s", where, accept=(0, 128)).strip()
        if not size.isdigit() or int(size) > MAX_FILE_BYTES:
            return None
        command = ["git", "show", where]
        try:
            done = subprocess.run(  # noqa: S603 - git from PATH, arguments the script built
                command, cwd=self.repo, capture_output=True, check=True, timeout=GIT_TIMEOUT
            )
            return done.stdout.decode("utf-8")
        except SHOW_ERRORS:
            return None

    def line(self, path: str, number: int) -> str | None:
        text = self.text(path)
        lines = doc_lines(text) if text is not None else []
        return lines[number - 1] if 1 <= number <= len(lines) else None


class Planner:
    """Sorts the judge's fixes into items, ADR lines and refusals."""

    def __init__(self, docs: BaseDocs, names: list[dict[str, object]]) -> None:
        self.docs, self.names = docs, names
        self.items: list[dict[str, object]] = []
        self.superseded: list[dict[str, object]] = []
        self.refused: list[dict[str, object]] = []
        self.seen: set[tuple[str, int]] = set()
        self.refused_bytes = self.adr_bytes = self.dropped = 0

    def refuse(self, path: str, line: int, reason: str) -> None:
        entry = {"path": path[:MAX_SHOWN], "line": line, "reason": reason}
        size = len(json.dumps(entry).encode()) + 2
        if len(self.refused) < MAX_REFUSED and self.refused_bytes + size <= MAX_LIST_BYTES:
            self.refused.append(entry)
            self.refused_bytes += size
        else:
            self.dropped += 1

    def add_adr(self, entry: dict[str, object]) -> None:
        where = (str(entry.get("path")), entry.get("line"))
        known = {(str(item["path"]), item["line"]) for item in self.superseded}
        size = len(json.dumps(entry).encode()) + 2
        if where in known:
            return
        if len(self.superseded) < MAX_SUPERSEDED and self.adr_bytes + size <= MAX_LIST_BYTES:
            self.superseded.append(entry)
            self.adr_bytes += size
        else:
            self.dropped += 1

    def _reason(self, path: str, line: int, *, old: str, new: str) -> str:
        if doc_role(path) != "edit":
            return NOT_ALLOWED
        if self.docs.line(path, line) != old:
            return "the line at the base differs"
        if not names_a_change(old, self.names):
            return "the line names no changed name"
        if "\n" in new or "\r" in new or len(new) > MAX_LINE:
            return "the new text is not one line"
        if new == old:
            return "the new text is the old one"
        if (path, line) in self.seen:
            return "another fix already targets this line"
        return ""

    def _adr_line(self, path: str, line: int, old: str) -> None:
        text = self.docs.text(path) or ""
        at_base = self.docs.line(path, line)
        self.add_adr(
            {
                "path": path,
                "line": line,
                "text": (old if at_base is None else at_base)[:500],
                "names": [str(n["name"]) for n in self.names if _has_token(str(n["name"]), old)],
                "status": adr_status(text),
            }
        )

    def take(self, fix: dict[str, object]) -> None:
        path, old, new = str(fix.get("path", "")), str(fix.get("old", "")), str(fix.get("new", ""))
        line = fix.get("line")
        line = line if isinstance(line, int) else 0
        if doc_role(path) == "adr":
            self._adr_line(path, line, old)
            return
        reason = self._reason(path, line, old=old, new=new)
        if reason:
            self.refuse(path, line, reason)
        elif len(self.items) >= MAX_ITEMS:
            self.refuse(path, line, f"more than {MAX_ITEMS} fixes")
        else:
            self.seen.add((path, line))
            entry = {"path": path, "line": line, "old": old, "new": new}
            self.items.append({"n": len(self.items) + 1, **entry, "reason": fix.get("reason", "")})


def _fence(*texts: str) -> str:
    longest = max((len(run) for text in texts for run in TICKS.findall(text)), default=0)
    return "`" * max(3, longest + 1)


def _item_block(item: dict[str, object]) -> str:
    old, new = str(item["old"]), str(item["new"])
    fence = _fence(old, new)
    head = f"{item['n']}. {item['path']}:{item['line']} - {item['reason']}"
    return f"{head}\n{fence}\n- {old}\n+ {new}\n{fence}"


def _adr_lines(entries: list[dict[str, object]]) -> list[str]:
    return [
        f"- {e['path']}:{e['line']} ({e.get('status') or 'no status'}): "
        f"{str(e.get('text', ''))[:MAX_SHOWN]}"
        for e in entries
    ]


def _sections(planner: Planner, notes: list[str]) -> list[str]:
    accepted = [e for e in planner.superseded if is_accepted(str(e.get("status", "")))]
    by_hand = [e for e in planner.superseded if not is_accepted(str(e.get("status", "")))]
    sections = []
    if accepted:
        sections.append(
            "\n".join(["Superseded wording (accepted ADRs, not edited):", *_adr_lines(accepted)])
        )
    if by_hand:
        heading = "ADR wording to change by hand, with the owner's confirmation:"
        sections.append("\n".join([heading, *_adr_lines(by_hand)]))
    if planner.refused:
        refused = [f"- {r['path']}:{r['line']}: {r['reason']}" for r in planner.refused]
        sections.append("\n".join(["Refused:", *refused]))
    if notes:
        sections.append("\n".join(["Not read or not checked:", *(f"- {n}" for n in notes)]))
    return sections


def render_message(planner: Planner, notes: list[str]) -> str:
    """The gate's text; items that do not fit in it are refused, so it shows all it approves."""
    blocks: list[str] = []
    size = 0
    shown: list[dict[str, object]] = []
    for item in planner.items:
        block = _item_block(item)
        if size + len(block.encode()) > MAX_MESSAGE - MESSAGE_RESERVE:
            planner.refuse(
                str(item["path"]), int(str(item["line"])), "past the gate message budget"
            )
            continue
        size += len(block.encode()) + 2
        shown.append(item | {"n": len(shown) + 1})
        blocks.append(_item_block(shown[-1]))
    planner.items = shown
    parts = []
    if shown:
        parts.append(
            f"doc-drift: {len(shown)} doc line(s) to fix. Approve to commit them on a new branch"
            " and open a docs-only PR; reject to open none."
        )
    parts += blocks + _sections(planner, notes)
    message = "\n\n".join(parts)
    encoded = message.encode()
    if len(encoded) > MAX_MESSAGE:
        message = encoded[: MAX_MESSAGE - 64].decode("utf-8", errors="ignore") + "\n[cut]"
    return message


def _judge(text: str) -> tuple[list[dict[str, object]], int]:
    if not text.strip():
        return [], 0
    try:
        value = json.loads(text)
    except ValueError as error:
        raise InputError(f"stdin: {error}") from None
    if not isinstance(value, dict) or not isinstance(value.get("fixes"), list):
        raise InputError("stdin: not the judge's reply (no fixes)")
    more = value.get("more")
    fixes = [fix for fix in value["fixes"] if isinstance(fix, dict)]
    return fixes, more if isinstance(more, int) else 0


def _notes(given: argparse.Namespace, more: int) -> list[str]:
    notes = [f"{n.get('path')}: {n.get('reason')}" for n in _json_list(given.notes, "--notes")]
    names_cut = _count(given.names_truncated, "--names-truncated")
    lines_cut = _count(given.mentions_truncated, "--mentions-truncated")
    if names_cut:
        notes.append(f"{names_cut} changed names past the cap were not checked")
    if given.patch_truncated.strip() == "true":
        notes.append("the change's diff was cut: some changed names may be missing")
    if lines_cut:
        notes.append(f"{lines_cut} doc lines past the prompt budget were not judged")
    if more:
        notes.append(f"the judge had {more} more fixes than it could list")
    return _within(notes, MAX_NOTES_BYTES)


def _within(notes: list[str], budget: int) -> list[str]:
    kept: list[str] = []
    size = 2
    for note in notes:
        size += len(json.dumps(note).encode()) + 2
        if size > budget:
            return [*kept, f"{len(notes) - len(kept)} more notes not shown"]
        kept.append(note)
    return kept


def plan_output(planner: Planner, notes: list[str]) -> dict[str, object]:
    """``plan``'s output from the sorted fixes: the gate message, the verdict, the lists."""
    message = render_message(planner, notes)
    if planner.dropped:
        notes = [*notes, f"{planner.dropped} more refused or ADR lines not listed"]
    reported = planner.superseded or planner.refused or notes
    verdict = "proposed" if planner.items else ("reported" if reported else "clean")
    return {
        "verdict": verdict,
        "fixes": len(planner.items),
        "items": planner.items,
        "superseded": planner.superseded,
        "refused": planner.refused,
        "notes": notes,
        "message": message,
    }


def plan(given: argparse.Namespace) -> dict[str, object]:
    fixes, more = _judge(_stdin())
    names = _json_list(given.names, "--names")
    planner = Planner(BaseDocs(Path(given.repo_path), given.base), names)
    for entry in _json_list(given.adr, "--adr"):
        planner.add_adr(entry)
    for fix in fixes:
        planner.take(fix)
    return plan_output(planner, _notes(given, more))


def _split_keeping_ends(text: str) -> list[str]:
    """The lines as ``doc_lines`` numbers them, each with its ending."""
    lines = re.split(r"(?<=\n)", text)
    return lines[:-1] if lines and lines[-1] == "" else lines


def _replace(path: Path, line: int, *, old: str, new: str) -> str:
    """Replace one line in the file, keeping its ending; the reason when it cannot."""
    try:
        text = path.read_bytes().decode("utf-8")
    except READ_ERRORS:
        return "not a readable UTF-8 file"
    lines = _split_keeping_ends(text)
    current = lines[line - 1] if 1 <= line <= len(lines) else None
    if current is None:
        return "the line moved since the plan"
    ending = current[len(current.rstrip("\r\n")) :]
    if current[: len(current) - len(ending)] != old:
        return "the line moved since the plan"
    lines[line - 1] = new + ending
    path.write_bytes("".join(lines).encode("utf-8"))
    return ""


def _target(worktree: Path, path: str) -> Path | None:
    candidate = worktree / path
    root = worktree.resolve()
    inside = candidate.resolve().is_relative_to(root)
    return candidate if inside and candidate.is_file() and not candidate.is_symlink() else None


class Applied:
    def __init__(self) -> None:
        self.done: list[dict[str, object]] = []
        self.skipped: list[dict[str, object]] = []

    def skip(self, item: dict[str, object], reason: str) -> None:
        self.skipped.append({"path": item.get("path"), "line": item.get("line"), "reason": reason})


def _items(text: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        value = json.loads(text)
    except ValueError as error:
        raise InputError(f"stdin: {error}") from None
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise InputError("stdin: not doc_fix.py plan's output (no items)")
    return value, [item for item in value["items"] if isinstance(item, dict)]


def _write(worktree: Path, items: list[dict[str, object]]) -> Applied:
    applied = Applied()
    for item in items:
        path, line = str(item.get("path", "")), item.get("line")
        target = _target(worktree, path) if doc_role(path) == "edit" else None
        if doc_role(path) != "edit":
            applied.skip(item, NOT_ALLOWED)
        elif target is None or not isinstance(line, int):
            applied.skip(item, "not a file in the worktree")
        elif reason := _replace(target, line, old=str(item.get("old")), new=str(item.get("new"))):
            applied.skip(item, reason)
        else:
            applied.done.append(item)
    return applied


def _found(worktree: Path, items: list[dict[str, object]]) -> Applied:
    """On a resumed run: the items whose new line the commit already holds."""
    applied = Applied()
    for item in items:
        path, line = str(item.get("path", "")), item.get("line")
        target = _target(worktree, path) if doc_role(path) == "edit" else None
        lines = doc_lines(target.read_text(encoding="utf-8")) if target else []
        holds = (
            isinstance(line, int) and 1 <= line <= len(lines) and lines[line - 1] == item.get("new")
        )
        if holds:
            applied.done.append(item)
        else:
            applied.skip(item, "not in the commit")
    return applied


def check_diff(worktree: Path, base: str, done: list[dict[str, object]]) -> None:
    """The commit holds only the planned lines, one for one, and nothing else is changed."""
    planned = Counter(str(item["path"]) for item in done)
    seen: set[str] = set()
    for row in _git(worktree, "diff", "--numstat", f"{base}..HEAD").splitlines():
        added, removed, path = row.split("\t", 2)
        want = str(planned.get(path, 0))
        if path not in planned or added != want or removed != want:
            raise GitFailedError(f"the commit changes {path} beyond the approved lines")
        seen.add(path)
    if seen != set(planned):
        raise GitFailedError(
            "the commit lacks approved lines: " + ", ".join(sorted(set(planned) - seen))
        )
    status = _git(worktree, "status", "--porcelain").strip()
    if status:
        raise GitFailedError(f"the worktree has changes beside the commit: {status[:500]}")


def _commit(worktree: Path, base: str, subject: str) -> bool:
    """``True`` when this run's commit already sits on ``base`` (a resumed run)."""
    head = _git(worktree, "rev-parse", "HEAD").strip()
    if head == base:
        return False
    commits = _git(worktree, "rev-list", f"{base}..HEAD").split()
    last = _git(worktree, "log", "-1", "--format=%s").strip()
    if len(commits) == 1 and last == subject:
        return True
    raise GitFailedError(f"the worktree's HEAD {head[:12]} is not the base {base[:12]}")


def _clean_note(note: str) -> str:
    kept = "".join(c for c in note if c in "\n\t" or not (ord(c) < 32 or 127 <= ord(c) <= 159))
    return kept.strip()[:MAX_NOTE]


def _regenerate(worktree: Path) -> str:
    makefile = worktree / "Makefile"
    try:
        text = makefile.read_text(encoding="utf-8") if makefile.is_file() else ""
    except READ_ERRORS:
        text = ""
    target = REGENERATE.search(text[:MAX_FILE_BYTES])
    if target:
        return (
            "Files generated from the docs are not regenerated by this run: run"
            f" `make {target.group(1)}` on this branch before merging."
        )
    return "Files generated from the docs, if any, are not regenerated by this run."


def summary_of(
    plan_value: dict[str, object], applied: Applied, *, label: str, note: str, hint: str
) -> str:
    """The PR's text: the lines changed, the ADR wording left, the refusals, the owner's note."""
    lines = [
        f"Fixes {len(applied.done)} doc line(s) that named contract names changed by {label}."
        " Docs only; every line was approved at the doc-drift gate.",
        "",
        *(
            f"- `{i['path']}:{i['line']}`: {str(i.get('reason', ''))[:MAX_SHOWN]}"
            for i in applied.done
        ),
    ]
    entries = plan_value.get("superseded")
    adr = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    accepted = [e for e in adr if is_accepted(str(e.get("status", "")))]
    by_hand = [e for e in adr if not is_accepted(str(e.get("status", "")))]
    if accepted:
        lines += ["", "Superseded wording (accepted ADRs, not edited):"]
        lines += [f"- `{e.get('path')}:{e.get('line')}`" for e in accepted]
    if by_hand:
        lines += ["", "ADR wording to change by hand, with the owner's confirmation:"]
        lines += [
            f"- `{e.get('path')}:{e.get('line')}` ({e.get('status') or 'no status'})"
            for e in by_hand
        ]
    refused = plan_value.get("refused")
    others = [r for r in refused if isinstance(r, dict)] if isinstance(refused, list) else []
    others += applied.skipped
    if others:
        lines += ["", "Refused or skipped:"]
        lines += [f"- `{r.get('path')}:{r.get('line')}`: {r.get('reason')}" for r in others]
    lines += ["", hint]
    body = "\n".join(lines)
    tail = ""
    if note:
        fence = _fence(note)
        tail = f"\n\nThe owner's note at the gate:\n{fence}text\n{note}\n{fence}\n"
    room = MAX_SUMMARY - len(tail)
    return (body if len(body) <= room else body[: room - 6] + "\n[cut]") + tail


def apply(given: argparse.Namespace) -> dict[str, object]:
    plan_value, items = _items(_stdin())
    worktree = Path(given.worktree)
    base = _git(worktree, "rev-parse", "--verify", f"{given.base}^{{commit}}").strip()
    subject = f"{given.subject_prefix}fix doc lines stale after {given.label}"
    if _commit(worktree, base, subject):
        applied = _found(worktree, items)
    else:
        applied = _write(worktree, items)
        files = sorted({str(item["path"]) for item in applied.done})
        if files:
            _git(worktree, "add", "--", *files)
            _git(worktree, "commit", "-q", "-m", subject, "--", *files)
    check_diff(worktree, base, applied.done)
    note, hint = _clean_note(given.note), _regenerate(worktree)
    summary = summary_of(plan_value, applied, label=given.label, note=note, hint=hint)
    return {
        "changes": len(applied.done),
        "files": sorted({str(item["path"]) for item in applied.done}),
        "skipped": applied.skipped,
        "summary": summary,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG)
    commands = parser.add_subparsers(dest="command", required=True)
    planned = commands.add_parser("plan")
    planned.add_argument("--repo-path", required=True)
    planned.add_argument("--base", required=True)
    for option in ("--names", "--adr", "--notes"):
        planned.add_argument(option, default="")
    for option in ("--names-truncated", "--patch-truncated", "--mentions-truncated"):
        planned.add_argument(option, default="")
    applying = commands.add_parser("apply")
    for option in ("--worktree", "--base", "--label", "--subject-prefix"):
        applying.add_argument(option, required=True)
    applying.add_argument("--note", default="")
    return parser


def main(argv: list[str]) -> int:
    given = _parser().parse_args(argv)
    try:
        found = plan(given) if given.command == "plan" else apply(given)
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
