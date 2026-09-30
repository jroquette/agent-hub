"""``rules.frontmatter``: closed frontmatter, rule globs that match, named agents and skills.

The port of the hub's old ``agent_config_lint.py`` frontmatter checks over the listed regular
instruction and plugin files (``config_lint``; spec AC-11.21, Q-5), each finding at line 1:

- An instruction or plugin file whose first line is ``---`` and that no later line closes is
  flagged, and nothing else is checked in it.
- A file under ``.claude/rules/`` with frontmatter needs a non-empty ``paths:`` list; each glob
  in it, its braces expanded (``{a,b}``) and ``/**/`` also tried as ``/``, must match (``fnmatch``,
  where ``*`` also crosses ``/``) a file or folder of the hub: the listed paths and the fixed paths
  present, and their folders (E31). A link counts as a path; nothing under a linked folder does.
- An agent or skill file (``config_lint.agent_skill_files``: regular files, never links, E1)
  needs a non-empty ``name`` and ``description``.

Scale: a glob longer than ``MAX_GLOB_LENGTH`` characters, or whose braces expand to more than
``MAX_GLOB_EXPANSIONS`` globs, is reported as such and not matched. A glob is translated once per
run, in time linear in its length (an ``[`` that ``fnmatch`` reads as a literal is closed first),
and matched only against the paths that start with its literal head, each path once as a file
and once for its folders, so no folder is ever built as a string. A run spends at most
``MAX_GLOB_CHARACTERS`` path characters on such matches (E33); the glob that would pass that
budget, and every glob after it not decided before, is reported as not checked. A file that is
not text is skipped: the runner reports it once (E28).
"""

import re
from bisect import bisect_left
from collections.abc import Callable, Iterable, Iterator
from fnmatch import translate
from typing import Final

from agent_hub.core.doctor.config_lint import (
    Frontmatter,
    Unterminated,
    agent_skill_files,
    file_text,
    instruction_files,
    known_paths,
    parse_frontmatter,
    plugin_files,
)
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import (
    RULE_MODULES,
    RULES_FRONTMATTER_RULE,
    Severity,
)
from agent_hub.core.hub_config.versions import cut_echo

RULES_FOLDER: Final = ".claude/rules/"
PATHS_FIELD: Final = "paths"
NAMED_FIELDS: Final = ("name", "description")
# The longest glob matched, and the most globs one glob's braces may expand to: each glob is
# matched against the hub's paths, so both bound the work one frontmatter line can ask for.
MAX_GLOB_LENGTH: Final = 256
MAX_GLOB_EXPANSIONS: Final = 64
# The path characters one run may spend matching globs (E33): a glob variant tried on one path
# costs the path's length + 1, as a match's time grows with it. Globs are tried in file order,
# then in their order in the file; the glob whose matching would pass the budget, and every glob
# not decided before it, gets a "not checked" finding instead.
MAX_GLOB_CHARACTERS: Final = 64_000_000

UNTERMINATED_MESSAGE: Final = "unterminated frontmatter"
UNTERMINATED_FIX: Final = "close the frontmatter with `---`"
PATHS_MESSAGE: Final = "rules frontmatter needs a non-empty `paths:` list"
PATHS_FIX: Final = "list the globs this rule applies to"
GLOB_FIX: Final = "fix or remove the glob"
UNMATCHED_MESSAGE: Final = "matches no file or folder in the hub"
UNCHECKED_MESSAGE: Final = "was not checked: the run's glob budget is spent"
UNCHECKED_FIX: Final = "use fewer or narrower globs"
UNNAMED_MESSAGE: Final = "agent/skill frontmatter needs `name` and `description`"
UNNAMED_FIX: Final = "add both fields"

# The old lint's brace group: the first ``{…}`` that holds no brace.
_BRACES: Final = re.compile(r"\{([^{}]*)\}")
_WILDCARD: Final = re.compile(r"[*?\[]")
_END_OF_TEXT: Final = r"\z"


def _rules_frontmatter(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    hub = snapshot.hub
    agents = frozenset(agent_skill_files(hub))
    globs = _Globs(lambda: known_paths(hub, config=snapshot.hub_config))
    for path in sorted((*instruction_files(hub), *plugin_files(hub))):
        text = file_text(hub.entries.get(path))
        if not isinstance(text, str):
            continue
        frontmatter = parse_frontmatter(text)
        if isinstance(frontmatter, Unterminated):
            yield _finding(path, message=UNTERMINATED_MESSAGE, fix=UNTERMINATED_FIX)
            continue
        if frontmatter is not None and path.startswith(RULES_FOLDER):
            yield from _paths_findings(path, frontmatter=frontmatter, globs=globs)
        if path in agents and not _is_named(frontmatter):
            yield _finding(path, message=UNNAMED_MESSAGE, fix=UNNAMED_FIX)


def _paths_findings(path: str, *, frontmatter: Frontmatter, globs: _Globs) -> Iterator[Finding]:
    listed = frontmatter.fields.get(PATHS_FIELD)
    if not isinstance(listed, tuple) or not listed:
        yield _finding(path, message=PATHS_MESSAGE, fix=PATHS_FIX)
        return
    for glob in listed:
        problem = globs.problem(glob)
        if problem is not None:
            message, fix = problem
            yield _finding(path, message=message, fix=fix)


def _is_named(frontmatter: Frontmatter | None) -> bool:
    # A field with no value and no items is an empty tuple: not given, as in the old lint.
    return frontmatter is not None and all(frontmatter.fields.get(name) for name in NAMED_FIELDS)


def _finding(path: str, *, message: str, fix: str) -> Finding:
    return RULES_FRONTMATTER.finding(path=path, line=1, message=message, fix=fix)


class _Globs:
    """Whether each glob matches a hub path or folder, each glob worked out once per run.

    The hub's paths are sorted on first use, so a hub whose rules name no glob never sorts them.
    Matching spends the run's budget (E33): a path a glob variant is tried on costs its length
    + 1, charged before the match; once a match does not fit, the glob being matched and every
    glob not yet worked out are not checked, even one that would cost nothing.
    """

    __slots__ = ("_budget", "_exhausted", "_paths", "_problems", "_source", "_spent")

    def __init__(self, source: Callable[[], Iterable[str]]) -> None:
        self._source = source
        self._paths: tuple[str, ...] | None = None
        self._problems: dict[str, tuple[str, str] | None] = {}
        self._budget = MAX_GLOB_CHARACTERS
        self._spent = 0
        self._exhausted = False

    def problem(self, glob: str) -> tuple[str, str] | None:
        """The message and fix of a flagged glob (too long, too many expansions, no match, not
        checked); ``None`` when it matches.
        """
        if glob not in self._problems:
            self._problems[glob] = self._first_problem(glob)
        return self._problems[glob]

    def _first_problem(self, glob: str) -> tuple[str, str] | None:
        shown = f"`{PATHS_FIELD}` glob `{cut_echo(glob)}`"
        if len(glob) > MAX_GLOB_LENGTH:
            return f"{shown} is longer than {MAX_GLOB_LENGTH} characters", GLOB_FIX
        expanded = _expanded(glob)
        if expanded is None:
            return f"{shown} expands to more than {MAX_GLOB_EXPANSIONS} globs", GLOB_FIX
        tried = dict.fromkeys(
            variant for each in expanded for variant in (each, each.replace("/**/", "/"))
        )
        if self._exhausted:
            return f"{shown} {UNCHECKED_MESSAGE}", UNCHECKED_FIX
        for variant in tried:
            matched = self._matches(variant)
            if matched is None:
                return f"{shown} {UNCHECKED_MESSAGE}", UNCHECKED_FIX
            if matched:
                return None
        return f"{shown} {UNMATCHED_MESSAGE}", GLOB_FIX

    def _matches(self, glob: str) -> bool | None:
        """Whether the glob matches; ``None`` when the budget runs out before it is known."""
        paths = self._sorted_paths()
        file_pattern, folder_pattern = _patterns(glob)
        wildcard = _WILDCARD.search(glob)
        head = glob if wildcard is None else glob[: wildcard.start()]
        # A match of the glob, file or folder, starts with its literal head, as does its path.
        for index in range(bisect_left(paths, head), len(paths)):
            path = paths[index]
            if not path.startswith(head):
                return False
            cost = len(path) + 1
            if self._spent + cost > self._budget:
                self._exhausted = True
                return None
            self._spent += cost
            if file_pattern.fullmatch(path) or folder_pattern.match(path):
                return True
        return False

    def _sorted_paths(self) -> tuple[str, ...]:
        if self._paths is None:
            self._paths = tuple(sorted(set(self._source())))
        return self._paths


def _patterns(glob: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """The glob as ``fnmatch`` reads it, as a whole path and as a path's folder.

    The folder pattern matches from a path's start up to one of its ``/``: a match there is a
    folder of the path that the glob matches whole. ``translate`` ends its patterns with ``\\z``.
    """
    whole = translate(_closed_brackets(glob))
    if not whole.endswith(_END_OF_TEXT):
        msg = f"fnmatch.translate gave an unexpected pattern for {glob!r}"
        raise ValueError(msg)
    return re.compile(whole), re.compile(f"{whole.removesuffix(_END_OF_TEXT)}/")


def _closed_brackets(glob: str) -> str:
    """The glob with each ``[`` that ``fnmatch`` reads as a literal written ``[[]``.

    ``fnmatch.translate`` looks for the ``]`` of every ``[`` to the end of the glob, so many
    unclosed ones cost the square of its length; ``[[]`` means the same and closes at once. An
    ``[`` is a literal when no ``]`` follows it (past a leading ``!`` and ``]``), and then so is
    every later one; the walk mirrors ``translate``'s, so it is linear.
    """
    index = 0
    while (opening := glob.find("[", index)) != -1:
        start = opening + 1
        if glob.startswith("!", start):
            start += 1
        if glob.startswith("]", start):
            start += 1
        closing = glob.find("]", start)
        if closing == -1:
            return glob[:opening] + glob[opening:].replace("[", "[[]")
        index = closing + 1
    return glob


def _expanded(glob: str) -> list[str] | None:
    """The old lint's brace expansion, in its order; ``None`` past ``MAX_GLOB_EXPANSIONS``.

    Each pending glob yields at least one expansion, so the count is known to pass the bound
    before the globs are built: at most ``MAX_GLOB_EXPANSIONS`` globs are ever done or pending,
    each reached through at most one group per two characters of the glob.
    """
    done: list[str] = []
    pending = [glob]
    while pending:
        current = pending.pop()
        group = _BRACES.search(current)
        if group is None:
            done.append(current)
            continue
        alternatives = group[1].split(",")
        if len(done) + len(pending) + len(alternatives) > MAX_GLOB_EXPANSIONS:
            return None
        head, tail = current[: group.start()], current[group.end() :]
        pending.extend(f"{head}{alternative}{tail}" for alternative in reversed(alternatives))
    return done


RULES_FRONTMATTER: Final = Rule(
    id=RULES_FRONTMATTER_RULE,
    severity=Severity.ERROR,
    summary=(
        "frontmatter of rules, agents and skills is closed, rule globs match hub files, "
        "and agents and skills have a name and description"
    ),
    module=RULE_MODULES.get(RULES_FRONTMATTER_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES, Read.PLUGIN_FILES}),
    check=_rules_frontmatter,
)
