"""``instructions.size``, ``.refs`` and ``.duplicates``: short, correct, unrepeated instructions.

The port of the hub's old ``agent_config_lint.py`` checks over the listed regular instruction
files (``config_lint``; spec AC-11.19, AC-11.20, Q-6). Lines are ``config_lint.text_lines``
(E29): ``\\n`` and ``\\r\\n`` end a line, a lone ``\\r`` does not.

- Size: a file over its line limit is flagged, with no line number. The defaults are
  ``AGENTS.md`` 100, ``CLAUDE.md`` 150 and ``CLAUDE.local.md`` 50 at the root and 80 for every
  nested instruction file (``*/*``); ``GEMINI.md`` has none. ``doctor.rules."instructions.size"
  .max_lines`` adds limits by key: a key with no glob character (``*``, ``?``, ``[``) is the exact
  path, with or without ``/`` (so a bare name is a root file; E30), any other key an ``fnmatch``
  over the path (where an unclosed ``[`` is a literal). A project key wins over a default one;
  within each, an exact key over a glob, then the longest glob, then the first in sorted order.
- Refs: a path, ``make`` target or ``pnpm`` script an instruction file names (below its
  frontmatter; an unterminated one hides the whole file) that does not exist is flagged at its
  line. A path is a link target (``[..](path#part)``) or a code span shaped like a path; it is
  skipped when it is a URL, ``mailto:``, ``~``, absolute or ``../`` path, a placeholder (``<x>``,
  ``path/to/``, ``...``, ``…``, ``$VAR``), ``origin/…``/``upstream/…``, a MIME type or a branch
  under ``project.branch_prefix``. It resolves, after cutting a ``::`` test id and a glob's tail
  (``@/`` read as ``src/``), against the listed files and their folders from the file's folder
  or the root, then by name (``.claude/worktrees``, ``node_modules``… are there by design), then
  as the end of a listed path, with ``.ts``, ``.tsx``, ``.js`` or ``.py`` added. Nothing out of
  the hub and no link is followed (D3). ``make`` targets are checked only when ``Makefile`` names
  one (``X :=`` counts, as in the old lint), ``pnpm`` scripts only when ``package.json`` is a JSON
  object with a non-empty ``scripts`` object (E11); either file as a link is not read.
- Duplicates: a line normalized as the old lint did (stripped, list markers and digits dropped
  from its start, blanks collapsed, lowercased) of 60 or more characters, not a table, fence or
  heading line, that an earlier file in sorted path order holds is flagged on the later file,
  naming the first ``path:line``. Frontmatter lines count too, as in the old lint (E11). Repeats
  within one file are not.

A file that is not text is skipped: the runner reports it once (E28).
"""

import posixpath
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fnmatch import translate
from types import MappingProxyType
from typing import Final

from agent_hub.core.doctor.config_lint import (
    Frontmatter,
    Unterminated,
    file_text,
    instruction_files,
    line_count,
    parse_frontmatter,
    text_lines,
)
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles, text_of
from agent_hub.core.hub_config.doctor_rules import (
    INSTRUCTIONS_DUPLICATES_RULE,
    INSTRUCTIONS_REFS_RULE,
    INSTRUCTIONS_SIZE_RULE,
    RULE_MODULES,
    Severity,
)
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes

DEFAULT_MAX_LINES: Final = MappingProxyType(
    {"AGENTS.md": 100, "CLAUDE.md": 150, "CLAUDE.local.md": 50, "*/*": 80}
)
SIZE_FIX: Final = "keep it a map, not a manual: move details to docs or the brain"
DUPLICATE_FIX: Final = "keep the instruction in one file and link to it"
DUPLICATE_MIN_LENGTH: Final = 60

_GLOB_CHARACTERS: Final = frozenset("*?[")
# What the old lint dropped from a line's start before comparing: list markers and numbers.
_LIST_MARKER: Final = "-*0123456789. "
# Table, fence and heading lines repeat by design.
_NOT_AN_INSTRUCTION: Final = ("|", "```", "#")
_BLANKS: Final = re.compile(r"\s+")


@dataclass(frozen=True, kw_only=True, slots=True)
class _Limits:
    """One source's limits: exact paths, and globs in the order they are tried."""

    exact: Mapping[str, int]
    globs: tuple[tuple[re.Pattern[str], int], ...]

    def of(self, path: str) -> int | None:
        limit = self.exact.get(path)
        if limit is not None:
            return limit
        return next((limit for glob, limit in self.globs if glob.match(path)), None)


def _limits(max_lines: Mapping[str, int]) -> _Limits:
    globs = sorted(
        (key for key in max_lines if not _GLOB_CHARACTERS.isdisjoint(key)),
        key=lambda key: (-len(key), key),
    )
    return _Limits(
        exact={key: limit for key, limit in max_lines.items() if _GLOB_CHARACTERS.isdisjoint(key)},
        globs=tuple((re.compile(translate(key)), max_lines[key]) for key in globs),
    )


_DEFAULT_LIMITS: Final = _limits(DEFAULT_MAX_LINES)


def _instructions_size(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    settings = snapshot.hub_config.doctor.rules.instructions_size
    max_lines = None if settings is None else settings.max_lines
    project = _limits(max_lines or {})
    for path in instruction_files(snapshot.hub):
        limit = project.of(path)
        if limit is None:
            limit = _DEFAULT_LIMITS.of(path)
        if limit is None:
            continue
        text = file_text(snapshot.hub.entries.get(path))
        if not isinstance(text, str):
            continue
        count = line_count(text)
        if count > limit:
            yield INSTRUCTIONS_SIZE.finding(
                path=path, message=f"{count} lines, limit {limit}", fix=SIZE_FIX
            )


def _instructions_duplicates(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    # Keyed by the normalized line, so the check stays linear in the files' total size.
    first: dict[str, tuple[str, int]] = {}
    for path in instruction_files(snapshot.hub):
        text = file_text(snapshot.hub.entries.get(path))
        if not isinstance(text, str):
            continue
        for number, line in enumerate(text_lines(text), start=1):
            key = _normalized(line)
            if key is None:
                continue
            first_path, first_line = first.setdefault(key, (path, number))
            if first_path != path:
                yield INSTRUCTIONS_DUPLICATES.finding(
                    path=path,
                    line=number,
                    message=f"duplicates {first_path}:{first_line}",
                    fix=DUPLICATE_FIX,
                )


def _normalized(line: str) -> str | None:
    """The line as the old lint compared it; ``None`` when too short or not an instruction."""
    key = _BLANKS.sub(" ", line.strip().lstrip(_LIST_MARKER)).lower()
    if len(key) < DUPLICATE_MIN_LENGTH or key.startswith(_NOT_AN_INSTRUCTION):
        return None
    return key


STALE_FIX: Final = "update the path or remove the line"
MAKE_FIX: Final = "use an existing target or add it"
PNPM_FIX: Final = "use an existing script"
MAKEFILE: Final = "Makefile"
PACKAGE_JSON: Final = "package.json"
# Paths an instruction may name that a hub never lists, by design.
IGNORED_BY_DESIGN: Final = frozenset(
    {".claude/worktrees", ".claude/settings.local.json", "node_modules", ".venv"}
)
PNPM_BUILTINS: Final = frozenset(
    {"install", "add", "exec", "dlx", "run", "i", "remove", "update", "why", "list", "store"}
)

# The old lint's shapes, word for word, except its link pattern and ``<…>`` placeholder, which
# are scanned by hand below: their backtracking rescans the rest of a line from every ``](`` or
# ``<``, quadratic on one long line.
_TICK: Final = re.compile(r"`([^`\n]+)`")
_PATHY: Final = re.compile(
    r"^(?:\./)?[\w.@-]+(?:/[\w.@*{},-]+)+/?$|^[\w.-]+\.(?:md|py|sh|ts|tsx|json|ya?ml|toml|ini|cfg|lock)$"
)
_MAKE: Final = re.compile(r"\bmake\s+([a-z][\w-]*)")
_PNPM: Final = re.compile(r"\bpnpm\s+(?:run\s+)?([a-z][\w:-]*)")
# Over the whole text, as the old lint did: ``\s*`` may cross a line, and ``X :=`` counts.
_MAKE_TARGET: Final = re.compile(r"^([a-zA-Z][\w-]*)\s*:", re.MULTILINE)
_PLACEHOLDER: Final = re.compile(r"path/to/|\.\.\.|…|\$\{?[A-Z_]+")
_NOT_A_PATH: Final = re.compile(r"^(?:origin|upstream)/|^(?:application|text|multipart)/")
_NOT_CHECKED: Final = ("http", "mailto:", "~", "/", "../")
_LINK_TARGET_STOP: Final = re.compile(r"[)#\s]")
_GLOB: Final = re.compile(r"[*{}]")
_EXTENSIONS: Final = ("", ".ts", ".tsx", ".js", ".py")

# Reversed path segments: a path ends with ``a/b`` when ``b`` then ``a`` can be walked.
type _Tails = dict[str, _Tails]


@dataclass(frozen=True, kw_only=True, slots=True)
class _HubPaths:
    """Every path looked at and every folder above one, and their ends, built once per run."""

    known: frozenset[str]
    tails: _Tails

    def resolves(self, ref: str, *, folder: str) -> bool:
        """Whether a reference names a listed file or folder, as the old lint resolved it."""
        ref = ref.split("::", 1)[0].rstrip("/")
        ref = f"src/{ref[2:]}" if ref.startswith("@/") else ref
        glob = _GLOB.search(ref)
        if glob is not None:
            ref = ref[: glob.start()].rstrip("/")
            if not ref:
                return True
        for base in (folder, ""):
            # Out of the hub, the result starts with "..", which is never known.
            where = posixpath.normpath(posixpath.join(base, ref))
            if where == "." or where in self.known:
                return True
        name = posixpath.normpath(ref)
        return name in IGNORED_BY_DESIGN or any(
            self._ends_a_path(name + extension) for extension in _EXTENSIONS
        )

    def _ends_a_path(self, candidate: str) -> bool:
        # A known path equal to the candidate or ending with "/" + candidate.
        node = self.tails
        for segment in reversed(candidate.split("/")):
            child = node.get(segment)
            if child is None:
                return False
            node = child
        return True


@dataclass(frozen=True, kw_only=True, slots=True)
class _RefContext:
    paths: _HubPaths
    make_targets: frozenset[str]
    pnpm_scripts: frozenset[str]
    branch_prefix: str


def _instructions_refs(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    hub = snapshot.hub
    files = instruction_files(hub)
    if not files:
        return
    context = _RefContext(
        paths=_hub_paths(hub),
        make_targets=_make_targets(hub),
        pnpm_scripts=_pnpm_scripts(hub),
        branch_prefix=snapshot.hub_config.project.branch_prefix,
    )
    for path in files:
        text = file_text(hub.entries.get(path))
        if isinstance(text, str):
            yield from _file_refs(path, text=text, context=context)


def _file_refs(path: str, *, text: str, context: _RefContext) -> Iterator[Finding]:
    lines = text_lines(text)
    start = _body_start(text, lines=lines)
    folder = posixpath.dirname(path)
    for number, line in enumerate(lines[start:], start=start + 1):
        for ref in _references(line):
            if not _is_checked(ref, branch_prefix=context.branch_prefix):
                continue
            if not context.paths.resolves(ref, folder=folder):
                yield INSTRUCTIONS_REFS.finding(
                    path=path,
                    line=number,
                    message=f"stale reference `{cut_echo(ref)}` (no such path)",
                    fix=STALE_FIX,
                )
        yield from _command_findings(path, number=number, line=line, context=context)


def _command_findings(
    path: str, *, number: int, line: str, context: _RefContext
) -> Iterator[Finding]:
    if context.make_targets:
        for target in _MAKE.findall(line):
            if target not in context.make_targets:
                yield INSTRUCTIONS_REFS.finding(
                    path=path,
                    line=number,
                    message=f"`make {cut_echo(target)}` is not a Makefile target",
                    fix=MAKE_FIX,
                )
    if context.pnpm_scripts:
        for script in _PNPM.findall(line):
            if script not in PNPM_BUILTINS and script not in context.pnpm_scripts:
                yield INSTRUCTIONS_REFS.finding(
                    path=path,
                    line=number,
                    message=f"`pnpm {cut_echo(script)}` is not a package.json script",
                    fix=PNPM_FIX,
                )


def _body_start(text: str, *, lines: tuple[str, ...]) -> int:
    """How many lines the frontmatter takes; an unterminated one takes the whole file."""
    frontmatter = parse_frontmatter(text)
    if isinstance(frontmatter, Frontmatter):
        return frontmatter.end
    if isinstance(frontmatter, Unterminated):
        return len(lines)
    return 0


def _references(line: str) -> list[str]:
    """The line's link targets, then its code spans shaped like a path, each stripped."""
    spans = (span for span in _TICK.findall(line) if _PATHY.match(span.strip()))
    return [ref.strip() for ref in (*_link_targets(line), *spans)]


def _link_targets(line: str) -> Iterator[str]:
    """What the old ``\\]\\(([^)#\\s]+)(?:#[^)]*)?\\)`` finds, in one pass over the line.

    A target runs from ``](`` over no ``)``, ``#`` or blank; it counts when ``)`` follows it, or
    ``#`` and a later ``)``. A ``](`` inside a failed target's run ends where that run ends, so
    each run is scanned once.
    """
    last_close = line.rfind(")")
    run_end = 0
    opener = line.find("](")
    while opener != -1:
        begin = opener + 2
        if begin >= run_end:
            stop = _LINK_TARGET_STOP.search(line, begin)
            run_end = len(line) if stop is None else stop.start()
        after = line[run_end : run_end + 1]
        if run_end > begin and (after == ")" or (after == "#" and last_close > run_end)):
            yield line[begin:run_end]
            opener = line.find("](", line.find(")", run_end) + 1)
        else:
            opener = line.find("](", opener + 1)


def _is_checked(ref: str, *, branch_prefix: str) -> bool:
    """Whether a reference is a path the rule checks: URLs, placeholders… are not."""
    return not (
        ref.startswith(_NOT_CHECKED)
        or _is_placeholder(ref)
        or _NOT_A_PATH.search(ref) is not None
        or ref.startswith(branch_prefix)
    )


def _is_placeholder(ref: str) -> bool:
    # ``<[^>]*>`` matches exactly when a ``>`` follows the first ``<``.
    opening = ref.find("<")
    return (opening != -1 and ref.find(">", opening) != -1) or (
        _PLACEHOLDER.search(ref) is not None
    )


def _hub_paths(hub: HubFiles) -> _HubPaths:
    """The listed and looked-at paths and their folders, as a set and as reversed segments."""
    known = set(hub.listed) | set(hub.entries)
    for path in tuple(known):
        cut = path.rfind("/")
        # Upwards until a folder already there: each folder is added once.
        while cut > 0 and path[:cut] not in known:
            known.add(path[:cut])
            cut = path.rfind("/", 0, cut)
    tails: _Tails = {}
    for path in known:
        node = tails
        for segment in reversed(path.split("/")):
            node = node.setdefault(segment, {})
    return _HubPaths(known=frozenset(known), tails=tails)


def _make_targets(hub: HubFiles) -> frozenset[str]:
    text = text_of(hub.entries.get(MAKEFILE))
    if text is None:
        return frozenset()
    return frozenset(_MAKE_TARGET.findall("\n".join(text_lines(text))))


def _pnpm_scripts(hub: HubFiles) -> frozenset[str]:
    """The ``scripts`` names of ``package.json``; none when it is absent, a link or invalid."""
    entry = hub.entries.get(PACKAGE_JSON)
    if not isinstance(entry, FileEntry) or entry.content is None:
        return frozenset()
    try:
        document = load_json_bytes(entry.content)
    except InvalidJsonError:
        return frozenset()
    scripts = document.get("scripts") if isinstance(document, dict) else None
    return frozenset(scripts) if isinstance(scripts, dict) else frozenset()


INSTRUCTIONS_SIZE: Final = Rule(
    id=INSTRUCTIONS_SIZE_RULE,
    severity=Severity.ERROR,
    summary="instruction files stay within their line limits",
    module=RULE_MODULES.get(INSTRUCTIONS_SIZE_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES}),
    check=_instructions_size,
)

INSTRUCTIONS_REFS: Final = Rule(
    id=INSTRUCTIONS_REFS_RULE,
    severity=Severity.ERROR,
    summary="paths, make targets and package scripts named in instruction files exist",
    module=RULE_MODULES.get(INSTRUCTIONS_REFS_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES}),
    check=_instructions_refs,
)

INSTRUCTIONS_DUPLICATES: Final = Rule(
    id=INSTRUCTIONS_DUPLICATES_RULE,
    severity=Severity.ERROR,
    summary="no instruction line of 60 or more characters is repeated in another instruction file",
    module=RULE_MODULES.get(INSTRUCTIONS_DUPLICATES_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES}),
    check=_instructions_duplicates,
)
