# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The contract names a change removed that nothing still declares, as JSON.

``contract.py --repo <dir> --sha <sha>`` runs in the hub (the node's default cwd). It reads
``hub.json`` → ``repos[]`` (the entry whose ``dir`` is ``<dir>``; its ``default_branch``, else
``project.default_branch``, else ``main``) and works in the repo's clone next to the hub, never
fetching (a script gets no token: fetch first). ``base`` is the local ``origin/<default>``.

- Merge mode (``--sha`` given): the diff from the commit's first parent to the commit; a name is
  gone when nothing at the commit still declares it.
- Monthly mode (``--sha`` blank): the diff from the last first-parent commit of ``base`` older
  than 30 days (``--now``, for tests, sets the clock; the empty tree when none) to ``base``; a
  name is gone when nothing at ``base`` declares it.

A changed name, one rule per kind: a CLI ``command`` (``.command("<n>")``, ``.command(name=
"<n>")``, ``add_typer(…, name="<n>")`` in ``*.py``), a ``make-target`` (``<n>:`` in ``Makefile``
or ``*.mk``), a ``flag`` (``--<n>`` in a code file), a ``config-key`` (``"<n>":`` in a
``*schema*.json``, JSON-Schema keywords apart), a ``skill`` (``skills/<n>/SKILL.md``), a
``workflow`` (``workflows/…/<n>.yaml``), a ``path`` (a deleted or renamed file), and a ``table``
or ``column`` an added migration's ``upgrade()`` drops or renames. Docs (``*.md``, ``*.txt``,
``*.rst``, ``*.adoc``, ``CHANGELOG*``) never keep a name alive, and tests never add one.

Prints ``{"mode", "sha", "base", "label", "hub", "repo_path", "count", "names": [{"kind",
"name", "new", "source"}], "skipped", "truncated", "patch_truncated"}``. Bad input (a config not
readable, a repo not in ``hub.json`` or not cloned, an unknown commit, no parent, no
``origin/<default>``) exits 2; a git failure exits 1. Both say why on stderr.
"""

import json
import re
from collections.abc import Callable, Iterable, Mapping
from typing import NamedTuple

KINDS = (
    "command",
    "make-target",
    "flag",
    "config-key",
    "skill",
    "workflow",
    "path",
    "table",
    "column",
)
MAX_NAMES = 100
MAX_NAMES_BYTES = 64 * 1024
MAX_NAME = 200
MAX_NEW = 5
MIN_NAME = 3
NAME = re.compile(r"^[A-Za-z0-9_./@:-]+$")
DOC_SUFFIXES = (".md", ".txt", ".rst", ".adoc")
SCHEMA_KEYWORDS = frozenset(
    {
        "$anchor", "$comment", "$defs", "$id", "$ref", "$schema", "additionalItems",
        "additionalProperties", "allOf", "anyOf", "const", "contains", "contentEncoding",
        "contentMediaType", "default", "definitions", "dependentRequired", "dependentSchemas",
        "deprecated", "description", "else", "enum", "examples", "exclusiveMaximum",
        "exclusiveMinimum", "format", "if", "items", "maxItems", "maxLength", "maxProperties",
        "maximum", "minItems", "minLength", "minProperties", "minimum", "multipleOf", "not",
        "oneOf", "pattern", "patternProperties", "prefixItems", "properties", "propertyNames",
        "readOnly", "required", "then", "title", "type", "unevaluatedItems",
        "unevaluatedProperties", "uniqueItems", "writeOnly",
    }
)  # fmt: skip
COMMAND = re.compile(r"""\.command\(\s*(?:name\s*=\s*)?["']([^"']+)["']""")
TYPER_GROUP = re.compile(r"""add_typer\(.*?\bname\s*=\s*["']([^"']+)["']""")
MAKE_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)")
FLAG = re.compile(r"(?<![A-Za-z0-9_-])(--[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9])(?![A-Za-z0-9_-])")
SCHEMA_KEY = re.compile(r'"([^"\\]+)"\s*:')
SKILL = re.compile(r"(?:^|/)skills/([^/]+)/SKILL\.md(?:\.tmpl)?$")
WORKFLOW = re.compile(r"(?:^|/)workflows/(?:[^/]+/)*([^/]+)\.(?:yaml|yml|json)$")
DEF = re.compile(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)")
HUNK = re.compile(r"^\@\@ [^@]* \@\@ ?(.*)$")
DROP_TABLE = re.compile(r"""op\.drop_table\(\s*["']([^"']+)["']""")
RENAME_TABLE = re.compile(r"""op\.rename_table\(\s*["']([^"']+)["']\s*,\s*["']([^"']+)["']""")
DROP_COLUMN = re.compile(r"""op\.drop_column\(\s*["'][^"']+["']\s*,\s*["']([^"']+)["']""")
ALTER_COLUMN = re.compile(
    r"""op\.alter_column\(\s*["'][^"']+["']\s*,\s*["']([^"']+)["'][^)]*?"""
    r"""new_column_name\s*=\s*["']([^"']+)["']""",
    re.DOTALL,
)
MIGRATION_DIRS = frozenset({"migrations", "versions", "alembic"})

Finder = Callable[[str], list[str]]


class Name(NamedTuple):
    """One contract name the change removed; ``new``: names of its kind the same file added."""

    kind: str
    name: str
    new: tuple[str, ...]
    source: str

    def as_json(self) -> dict[str, object]:
        return {"kind": self.kind, "name": self.name, "new": list(self.new), "source": self.source}


class Extracted(NamedTuple):
    names: list[Name]
    skipped: int


class FileChange(NamedTuple):
    """One file's ``-U0`` hunks: removed and added lines, and those added in ``upgrade()``."""

    removed: list[str]
    added: list[str]
    upgrade: list[str]


def is_doc(path: str) -> bool:
    """A doc file never keeps a name alive: generated docs would otherwise hide every drift."""
    base = path.rsplit("/", 1)[-1]
    return base.lower().endswith(DOC_SUFFIXES) or base.upper().startswith("CHANGELOG")


def is_test(path: str) -> bool:
    parts = path.split("/")
    base = parts[-1]
    return (
        any(part in {"tests", "test", "__tests__"} for part in parts[:-1])
        or base.startswith("test_")
        or base.endswith(("_test.py", "_test.go"))
        or ".test." in base
        or ".spec." in base
    )


def is_makefile(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return base in {"Makefile", "GNUmakefile", "makefile"} or base.endswith(".mk")


def is_schema(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return base.endswith(".json") and "schema" in base.lower()


def is_migration(path: str) -> bool:
    return path.endswith(".py") and bool(MIGRATION_DIRS.intersection(path.split("/")[:-1]))


def _commands(line: str) -> list[str]:
    return COMMAND.findall(line) + TYPER_GROUP.findall(line)


def _make_targets(line: str) -> list[str]:
    found = MAKE_TARGET.match(line)
    return [found.group(1)] if found and not found.group(1).startswith(".") else []


def _schema_keys(line: str) -> list[str]:
    return [key for key in SCHEMA_KEY.findall(line) if key not in SCHEMA_KEYWORDS]


def _line_rules(path: str) -> list[tuple[str, Finder]]:
    """The (kind, finder) pairs that apply to a file's changed lines."""
    if is_doc(path) or is_test(path):
        return []
    rules: list[tuple[str, Finder]] = []
    if path.endswith(".py"):
        rules.append(("command", _commands))
    if is_makefile(path):
        rules.append(("make-target", _make_targets))
    if is_schema(path):
        rules.append(("config-key", _schema_keys))
    rules.append(("flag", FLAG.findall))
    return rules


class _PatchReader:
    """Reads a ``git diff -U0`` patch line by line, keeping the function each hunk is in."""

    def __init__(self) -> None:
        self.changes: dict[str, FileChange] = {}
        self.current: FileChange | None = None
        self.old_path = ""
        self.function = ""

    def header(self, line: str) -> bool:
        if line.startswith("diff --git "):
            self.current, self.old_path, self.function = None, "", ""
        elif line.startswith("--- ") and self.current is None:
            self.old_path = line[4:].removeprefix("a/")
        elif line.startswith("+++ ") and self.current is None:
            new_path = line[4:].removeprefix("b/")
            path = self.old_path if new_path == "/dev/null" else new_path
            self.current = self.changes.setdefault(path, FileChange([], [], []))
        else:
            return False
        return True

    def body(self, line: str, current: FileChange) -> None:
        if hunk := HUNK.match(line):
            self.function = _function(hunk.group(1), self.function)
            return
        text = line[1:]
        if line.startswith("-"):
            current.removed.append(text)
        elif line.startswith("+"):
            current.added.append(text)
        else:
            return
        self.function = _function(text, self.function)
        if line.startswith("+") and self.function == "upgrade":
            current.upgrade.append(text)

    def read(self, line: str) -> None:
        if not self.header(line) and self.current is not None:
            self.body(line, self.current)


def split_patch(patch: str) -> dict[str, FileChange]:
    """A ``git diff -U0`` patch, file by file (the new path; the old one for a deletion)."""
    reader = _PatchReader()
    for line in patch.splitlines():
        reader.read(line)
    return reader.changes


def _function(text: str, current: str) -> str:
    found = DEF.match(text)
    return found.group(1) if found else current


def _found(finder: Finder, lines: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for line in lines:
        for name in finder(line):
            seen.setdefault(name, None)
    return list(seen)


def _line_names(path: str, change: FileChange) -> list[Name]:
    names: list[Name] = []
    for kind, finder in _line_rules(path):
        removed, added = _found(finder, change.removed), _found(finder, change.added)
        new = tuple(name for name in added if name not in removed)[:MAX_NEW]
        names.extend(Name(kind, name, new, path) for name in removed if name not in added)
    return names


def _migration_names(path: str, change: FileChange) -> list[Name]:
    text = "\n".join(change.upgrade)
    names = [Name("table", table, (), path) for table in DROP_TABLE.findall(text)]
    names += [Name("table", old, (new,), path) for old, new in RENAME_TABLE.findall(text)]
    names += [Name("column", column, (), path) for column in DROP_COLUMN.findall(text)]
    names += [Name("column", old, (new,), path) for old, new in ALTER_COLUMN.findall(text)]
    return names


def _renamed(pattern: re.Pattern[str], old: str, new: str) -> tuple[str, tuple[str, ...]] | None:
    """The name ``pattern`` reads in ``old`` when the row removes it, with its new name."""
    before = pattern.search(old)
    if before is None:
        return None
    after = pattern.search(new) if new else None
    if after is not None and after.group(1) == before.group(1):
        return None
    return before.group(1), (after.group(1),) if after else ()


def _row_names(status: str, old: str, new: str) -> list[Name]:
    if status not in {"D", "R"}:
        return []
    names = [Name("path", old, (new,) if new else (), old)]
    if (skill := _renamed(SKILL, old, new)) is not None:
        names.append(Name("skill", skill[0], skill[1], old))
    if "/fixtures/" not in f"/{old}" and (flow := _renamed(WORKFLOW, old, new)) is not None:
        names.append(Name("workflow", flow[0], flow[1], old))
    return names


def _acceptable(name: str) -> bool:
    return len(name.lstrip("-")) >= MIN_NAME and len(name) <= MAX_NAME and bool(NAME.match(name))


def names_from(status: list[tuple[str, str, str]], patch: str) -> Extracted:
    """Decision 3's rules on ``--name-status`` rows (status letter, old path, new path) and a
    ``-U0`` patch: every removed name once, by kind; names too short or odd are only counted."""
    found: list[Name] = []
    added = {old for letter, old, _ in status if letter == "A"}
    for letter, old, new in status:
        found.extend(_row_names(letter[:1], old, new))
    for path, change in split_patch(patch).items():
        found.extend(_line_names(path, change))
        if path in added and is_migration(path):
            found.extend(_migration_names(path, change))
    unique: dict[tuple[str, str], Name] = {}
    skipped = 0
    for name in found:
        if not _acceptable(name.name):
            skipped += 1
        else:
            unique.setdefault((name.kind, name.name), name)
    return Extracted(list(unique.values()), skipped)


def _declares_command(name: str, text: str) -> bool:
    quoted = re.escape(name)
    return bool(
        re.search(rf"""\.command\(\s*(?:name\s*=\s*)?["']{quoted}["']""", text)
        or re.search(rf"""\bname\s*=\s*["']{quoted}["']""", text)
    )


def _has_token(name: str, text: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", text))


def still_declared(kind: str, name: str, files: Mapping[str, str]) -> bool:
    """Whether ``files`` (path → text, the tree at the new commit) still declare the name."""
    code = {path: text for path, text in files.items() if not is_doc(path)}
    if kind == "command":
        return any(_declares_command(name, t) for p, t in code.items() if p.endswith(".py"))
    if kind == "make-target":
        target = re.compile(rf"^{re.escape(name)}\s*:(?!=)", re.MULTILINE)
        return any(target.search(text) for path, text in code.items() if is_makefile(path))
    if kind == "flag":
        return any(_has_token(name, text) for text in code.values())
    if kind == "config-key":
        key = re.compile(rf'"{re.escape(name)}"\s*:')
        return any(key.search(text) for path, text in code.items() if is_schema(path))
    if kind == "skill":
        return any((m := SKILL.search(path)) and m.group(1) == name for path in files)
    if kind == "workflow":
        return any((m := WORKFLOW.search(path)) and m.group(1) == name for path in files)
    if kind == "path":
        return name in files
    return False


def capped(names: list[Name]) -> tuple[list[Name], int]:
    """At most ``MAX_NAMES`` names whose JSON stays within ``MAX_NAMES_BYTES``; the rest counted."""
    kept: list[Name] = []
    size = 2
    for name in names[:MAX_NAMES]:
        size += len(json.dumps(name.as_json()).encode()) + 2
        if size > MAX_NAMES_BYTES:
            break
        kept.append(name)
    return kept, len(names) - len(kept)
