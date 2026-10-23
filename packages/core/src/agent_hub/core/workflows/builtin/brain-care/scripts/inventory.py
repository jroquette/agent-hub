# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Measure the hub's always-loaded context for a brain-care ``context`` run, as JSON.

``inventory.py [--root HUB]`` does steps 1 and 2 of the ``context-audit`` skill on the hub (a
hub PR cannot trim a repo's files) and checks its hard limits, so the run names the files past
them without relying on a model:

- memory: ``CLAUDE.md`` and ``AGENTS.md``, the files they import (``@path``, up to four levels),
  and the rules in ``.claude/rules/*.md`` without a ``paths:`` filter;
- each skill's ``description`` (``.claude/skills/*/SKILL.md``; one with
  ``disable-model-invocation: true`` loads only when typed, so it stays out of the total), and
  its body apart (a body loads only when used: never in the total);
- each agent's ``description`` (``.claude/agents/*.md``).

Tokens are an estimate: characters divided by four, rounded up. Limits: a memory file over 200
lines, a skill description over 1,024 characters, agent descriptions together near 15,000
tokens (90% of it). ``hub.lock`` says which files are managed (changed only through
``hub.json`` or a seeded sibling, then ``hub sync``).

Reads at most 500 files, each at most 1 MiB in UTF-8, every resolved path under the root; a file
it cannot read is listed in ``unreadable`` with the reason. Prints ``{"total_tokens", "files":
[{"path", "kind", "lines", "chars", "tokens", "managed"}] (the 50 largest), "over": [{"path",
"rule", "value", "limit"}], "unreadable": [{"path", "reason"}], "summary"}``. A root that is not
a folder exits 2.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

PROG = "inventory.py"
MAX_FILES = 500
MAX_FILE_BYTES = 1024 * 1024
MAX_IMPORT_DEPTH = 4
MAX_LISTED = 50
MEMORY_LINES = 200
DESCRIPTION_CHARS = 1024
AGENT_TOKENS = 15000
NEAR = 0.9
MEMORY_FILES = ("CLAUDE.md", "AGENTS.md")
IMPORT = re.compile(r"(?<![\w`])@([~\w./-]+)")
LOADED_KINDS = frozenset({"memory", "import", "rule", "skill", "agent"})
MEMORY_KINDS = frozenset({"memory", "import", "rule"})
SKILL_KINDS = frozenset({"skill", "skill (typed only)"})


class Entry(NamedTuple):
    path: str
    kind: str
    lines: int
    chars: int


class UnreadableError(Exception):
    """A file the inventory cannot read; its message is the reason."""


def tokens(chars: int) -> int:
    return (chars + 3) // 4


def _front(text: str) -> tuple[dict[str, str], str]:
    """A front matter's keys (a folded ``>``/``|`` value joined) and the body after it."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    closing = next((n for n, line in enumerate(lines[1:], 1) if line.strip() == "---"), 0)
    fields: dict[str, str] = {}
    key = ""
    for line in lines[1:closing]:
        if key and line[:1] in (" ", "\t"):
            fields[key] = (fields[key] + " " + line.strip()).strip()
            continue
        name, sep, value = line.partition(":")
        key = name.strip() if sep else ""
        if key:
            value = value.strip()
            fields[key] = "" if value in (">", ">-", "|", "|-") else value.strip("\"'")
    return fields, "\n".join(lines[closing + 1 :]) if closing else text


class _Reader:
    """The hub's files, read once each, inside the root and the bounds."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.seen: set[Path] = set()
        self.unreadable: list[dict[str, str]] = []

    def shown(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def read(self, path: Path, *, named: str) -> str | None:
        """The file's text, or ``None`` (listed in ``unreadable``, or already read)."""
        try:
            return self._text(path, named=named)
        except UnreadableError as error:
            self.unreadable.append({"path": named, "reason": str(error)})
            return None

    def _text(self, path: Path, *, named: str) -> str | None:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or named.startswith("~"):
            raise UnreadableError("outside the hub")
        if resolved in self.seen:
            return None
        if not resolved.is_file():
            raise UnreadableError("missing")
        if len(self.seen) >= MAX_FILES:
            raise UnreadableError(f"past {MAX_FILES} files")
        self.seen.add(resolved)
        try:
            if resolved.stat().st_size > MAX_FILE_BYTES:
                raise UnreadableError("larger than 1 MiB")
            return resolved.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise UnreadableError("not UTF-8") from None
        except OSError as error:
            raise UnreadableError(error.strerror or str(error)) from None


def _entry(path: str, kind: str, text: str) -> Entry:
    return Entry(path=path, kind=kind, lines=len(text.splitlines()), chars=len(text))


def _memory(reader: _Reader, path: Path, *, kind: str, depth: int) -> list[Entry]:
    """A memory file and the files it imports, depth first."""
    text = reader.read(path, named=reader.shown(path.resolve()))
    if text is None:
        return []
    return [
        _entry(reader.shown(path.resolve()), kind, text),
        *_imports(reader, path, text, depth=depth),
    ]


def _imports(reader: _Reader, path: Path, text: str, *, depth: int) -> list[Entry]:
    """The files ``text`` imports (``@path``, relative to ``path``'s folder)."""
    found: list[Entry] = []
    for name in IMPORT.findall(text):
        target = (path.parent / name).resolve()
        if name.startswith("~") or not target.is_relative_to(reader.root):
            reader.unreadable.append({"path": name, "reason": "outside the hub"})
        elif depth >= MAX_IMPORT_DEPTH:
            reader.unreadable.append(
                {"path": reader.shown(target), "reason": "deeper than 4 imports"}
            )
        else:
            found += _memory(reader, target, kind="import", depth=depth + 1)
    return found


def _rules(reader: _Reader) -> list[Entry]:
    """The always-loaded rules (no ``paths:`` filter) and what they import."""
    found: list[Entry] = []
    for path in sorted((reader.root / ".claude/rules").glob("*.md")):
        text = reader.read(path, named=reader.shown(path))
        if text is not None and "paths" not in _front(text)[0]:
            found += [
                _entry(reader.shown(path), "rule", text),
                *_imports(reader, path, text, depth=0),
            ]
    return found


def _described(reader: _Reader, pattern: str, kind: str) -> list[Entry]:
    """Each skill's or agent's description; a skill's body apart."""
    found: list[Entry] = []
    for path in sorted(reader.root.glob(pattern)):
        shown = f"{pattern.split('*')[0]}{path.relative_to(reader.root / pattern.split('*')[0])}"
        text = reader.read(path, named=shown)
        if text is None:
            continue
        fields, body = _front(text)
        described = " ".join(v for v in (fields.get("description"), fields.get("when_to_use")) if v)
        typed = kind == "skill" and fields.get("disable-model-invocation") == "true"
        found.append(_entry(shown, f"{kind} (typed only)" if typed else kind, described))
        if kind == "skill":
            found.append(_entry(shown, "skill body", body))
    return found


def _limit(path: str, rule: str, *, value: int, limit: int) -> dict[str, object]:
    return {"path": path, "rule": rule, "value": value, "limit": limit}


def _over(entries: list[Entry]) -> list[dict[str, object]]:
    """The entries past a known limit, in the order read; the agents' total last."""
    over: list[dict[str, object]] = []
    for entry in entries:
        if entry.kind in MEMORY_KINDS and entry.lines > MEMORY_LINES:
            rule = f"memory file over {MEMORY_LINES} lines"
            over.append(_limit(entry.path, rule, value=entry.lines, limit=MEMORY_LINES))
        if entry.kind in SKILL_KINDS and entry.chars > DESCRIPTION_CHARS:
            rule = "skill description over 1,024 characters"
            over.append(_limit(entry.path, rule, value=entry.chars, limit=DESCRIPTION_CHARS))
    agents = sum(tokens(entry.chars) for entry in entries if entry.kind == "agent")
    if agents >= AGENT_TOKENS * NEAR:
        rule = "agent descriptions near 15,000 tokens"
        over.append(_limit(".claude/agents/", rule, value=agents, limit=AGENT_TOKENS))
    return over


def _lines(heading: str, items: list[str]) -> list[str]:
    return [heading, *items] if items else []


def _summary(
    total: int,
    listed: list[dict[str, object]],
    *,
    over: list[dict[str, object]],
    unreadable: list[dict[str, str]],
) -> str:
    """The gate's text: the total, the five largest parts, every file past a limit."""
    largest = [i for i in listed if i["kind"] in LOADED_KINDS][:5]
    return "\n".join(
        [
            f"Always-loaded context: about {total} tokens (an estimate: characters / 4).",
            *_lines(
                "Largest parts:",
                [f"- {i['path']} ({i['kind']}): {i['tokens']} tokens" for i in largest],
            ),
            "Over the limits:" if over else "Over the limits: none.",
            *(f"- {i['path']}: {i['rule']} ({i['value']}; limit {i['limit']})" for i in over),
            *_lines("Not read:", [f"- {i['path']}: {i['reason']}" for i in unreadable]),
        ]
    )


def inventory(root: Path) -> dict[str, object]:
    reader = _Reader(root)
    entries: list[Entry] = []
    for name in MEMORY_FILES:
        if (reader.root / name).is_file():
            entries += _memory(reader, reader.root / name, kind="memory", depth=0)
    entries += _rules(reader)
    entries += _described(reader, ".claude/skills/*/SKILL.md", "skill")
    entries += _described(reader, ".claude/agents/*.md", "agent")
    managed = _managed(reader)
    listed = [
        {
            "path": e.path,
            "kind": e.kind,
            "lines": e.lines,
            "chars": e.chars,
            "tokens": tokens(e.chars),
            "managed": e.path in managed or _target(reader, e.path) in managed,
        }
        for e in sorted(entries, key=lambda e: -e.chars)
    ][:MAX_LISTED]
    total = sum(tokens(e.chars) for e in entries if e.kind in LOADED_KINDS)
    over = _over(entries)
    return {
        "total_tokens": total,
        "files": listed,
        "over": over,
        "unreadable": reader.unreadable,
        "summary": _summary(total, listed, over=over, unreadable=reader.unreadable),
    }


def _target(reader: _Reader, path: str) -> str:
    resolved = (reader.root / path).resolve()
    return reader.shown(resolved) if resolved.is_relative_to(reader.root) else path


def _managed(reader: _Reader) -> set[str]:
    """The paths ``hub.lock`` records as managed; none when it cannot be read."""
    lock = reader.root / "hub.lock"
    try:
        if not lock.is_file() or lock.stat().st_size > MAX_FILE_BYTES:
            return set()
        document = json.loads(lock.read_text(encoding="utf-8"))
    except OSError:
        return set()
    except ValueError:  # not UTF-8, or not JSON
        return set()
    found = document.get("files") if isinstance(document, dict) else None
    if not isinstance(found, dict):
        return set()
    return {
        path
        for path, facts in found.items()
        if isinstance(facts, dict) and facts.get("ownership") == "managed"
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--root", default=".")
    given = parser.parse_args(argv)
    root = Path(given.root)
    if not root.is_dir():
        print(f"{PROG}: {root} is not a folder", file=sys.stderr)
        return 2
    print(json.dumps(inventory(root)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
