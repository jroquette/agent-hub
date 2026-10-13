"""What a skill's body says it does, derived from its text (AGH-164, S6, P5): steps, a table of
contents and the items it names.

Heuristic and labelled so in the UI. A step is a top-level ordered list item: a line at column 0
matching ``STEP_LINE`` outside fenced code (the web numbers ``#step-<n>`` anchors by the same rule).
Fenced code is ignored, except that ``!`…``` spans and ```` ```! ```` blocks are counted as
dynamic context (they run when the skill is invoked; here they are text, never run).
"""

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Final

from agent_hub.core.redaction.redact import clip
from agent_hub.core.skills.skill_view import SkillStructure, Step, StepTag, TocEntry, bare_name

MAX_STEPS: Final = 200
MAX_STEP_TITLE_CHARS: Final = 80
MAX_REFERENCES: Final = 200
MAX_TOC_ENTRIES: Final = 200

# A step: an ordered list item at column 0 (P5; the web's rule).
STEP_LINE: Final = re.compile(r"^\d{1,9}[.)]\s")
# The text tags of a step (S6); ``agent`` comes from the catalog, not from a pattern.
STEP_PATTERNS: Final[Mapping[StepTag, re.Pattern[str]]] = {
    "gate": re.compile(r"\bgates?\b|\bapproves\b", re.IGNORECASE),
    "command": re.compile(r"`((?:make|\./hub)(?:[ \t][^`]*)?)`"),
    "script": re.compile(r"\$\{CLAUDE_SKILL_DIR\}/[\w./-]*\w|(?<![\w/}])scripts/[\w./-]*\w"),
    "human": re.compile(r"\bask the user\b|\buser approves\b", re.IGNORECASE),
}
# Claude Code's built-in slash commands: naming one is not a missing skill.
CLAUDE_CODE_COMMANDS: Final = frozenset(
    {
        "add-dir",
        "agents",
        "bashes",
        "bug",
        "clear",
        "compact",
        "config",
        "context",
        "cost",
        "doctor",
        "exit",
        "export",
        "help",
        "hooks",
        "ide",
        "init",
        "install-github-app",
        "login",
        "logout",
        "mcp",
        "memory",
        "model",
        "output-style",
        "permissions",
        "plugin",
        "pr-comments",
        "privacy-settings",
        "release-notes",
        "resume",
        "review",
        "rewind",
        "security-review",
        "status",
        "statusline",
        "terminal-setup",
        "todos",
        "upgrade",
        "usage",
        "vim",
    }
)

_FENCE_OPEN: Final = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE: Final = re.compile(r"`+|~+")
_HEADING: Final = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_DYNAMIC_SPAN: Final = re.compile(r"!`[^`]*`")
_STEP_PREFIX: Final = re.compile(r"^\d{1,9}[.)]\s+")
_BOLD_TITLE: Final = re.compile(r"^\*\*(.+?)\*\*")
_SKILL_REF: Final = re.compile(
    r"(?<![^\s`(])/([A-Za-z0-9][A-Za-z0-9_-]*(?::[A-Za-z0-9][A-Za-z0-9_-]*)?)(?![\w/-]|\.\w)"
)
_BACKTICKED_NAME: Final = re.compile(r"`([A-Za-z0-9][A-Za-z0-9_-]*)`")
_NAMED_AGENT: Final = re.compile(r"`([A-Za-z0-9][A-Za-z0-9_-]*)`[ \t]+(?:sub)?agent\b")


@dataclass(frozen=True, kw_only=True, slots=True)
class References:
    """The cataloged agents and skills a body names, in first-seen order, and the names it
    uses that are not found (``/name`` for a skill, the bare name for an agent)."""

    agents: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _BodyLine:
    text: str
    fenced: bool
    dynamic_fence: bool = False


def _lines(body: str) -> Iterator[_BodyLine]:
    """Each line of ``body`` and whether it is fenced code (fence lines included)."""
    marker: str | None = None
    for text in body.splitlines():
        if marker is not None:
            trimmed = text.strip()
            if trimmed.startswith(marker) and _FENCE_CLOSE.fullmatch(trimmed):
                marker = None
            yield _BodyLine(text, fenced=True)
            continue
        opened = _FENCE_OPEN.match(text)
        if opened is not None:
            marker = opened.group(1)
            dynamic = marker.startswith("`") and opened.group(2).strip().startswith("!")
            yield _BodyLine(text, fenced=True, dynamic_fence=dynamic)
            continue
        yield _BodyLine(text, fenced=False)


def _prose(lines: Iterable[_BodyLine]) -> str:
    """The unfenced text of ``lines``, dynamic-context spans removed."""
    return "\n".join(_DYNAMIC_SPAN.sub(" ", line.text) for line in lines if not line.fenced)


class _Unique:
    def __init__(self) -> None:
        self.items: list[str] = []
        self._seen: set[str] = set()

    def add(self, item: str) -> None:
        if item not in self._seen and len(self.items) < MAX_REFERENCES:
            self._seen.add(item)
            self.items.append(item)

    def values(self) -> tuple[str, ...]:
        return tuple(self.items)


def _named_agents(text: str, agents: frozenset[str]) -> tuple[str, ...]:
    found = _Unique()
    for match in _BACKTICKED_NAME.finditer(text):
        if match.group(1) in agents:
            found.add(match.group(1))
    return found.values()


def _named_skills(text: str, skills: frozenset[str]) -> tuple[str, ...]:
    found = _Unique()
    for match in _SKILL_REF.finditer(text):
        name = bare_name(match.group(1))
        if name in skills:
            found.add(name)
    return found.values()


def _commands(text: str) -> tuple[str, ...]:
    found = _Unique()
    for match in STEP_PATTERNS["command"].finditer(text):
        found.add(match.group(1).strip())
    return found.values()


def _scripts(text: str) -> tuple[str, ...]:
    found = _Unique()
    for match in STEP_PATTERNS["script"].finditer(text):
        found.add(match.group(0))
    return found.values()


def references(body: str, *, agents: frozenset[str], skills: frozenset[str]) -> References:
    """The items ``body`` names outside fenced code: cataloged ``agents`` named in backticks,
    cataloged ``skills`` named as ``/name`` (a ``<plugin>:`` prefix stripped), and unresolved
    names: a ``/name`` neither cataloged nor a Claude Code command, a ``\\`name\\` agent`` not
    cataloged. At most ``MAX_REFERENCES`` of each."""
    text = _prose(_lines(body))
    unresolved = _Unique()
    for match in re.finditer(f"{_SKILL_REF.pattern}|{_NAMED_AGENT.pattern}", text):
        skill, agent = match.group(1), match.group(2)
        if skill is not None:
            name = bare_name(skill)
            if name not in skills and name not in CLAUDE_CODE_COMMANDS:
                unresolved.add(f"/{name}")
        elif agent is not None and agent not in agents:
            unresolved.add(agent)
    return References(
        agents=_named_agents(text, agents),
        skills=_named_skills(text, skills),
        unresolved=unresolved.values(),
    )


def table_of_contents(body: str) -> tuple[TocEntry, ...]:
    """The headings of ``body`` outside fenced code, in order (at most ``MAX_TOC_ENTRIES``);
    headings with no text are left out. The web computes their anchors (P5)."""
    entries: list[TocEntry] = []
    for line in _lines(body):
        found = None if line.fenced else _HEADING.match(line.text)
        text = (found.group(2) or "").strip() if found else ""
        if found and text:
            entries.append(TocEntry(level=len(found.group(1)), text=text))
            if len(entries) == MAX_TOC_ENTRIES:
                break
    return tuple(entries)


@dataclass
class _StepText:
    lines: list[_BodyLine] = field(default_factory=list)


def _step_texts(body: str) -> list[_StepText]:
    steps: list[_StepText] = []
    current: _StepText | None = None
    for line in _lines(body):
        at_column_zero = bool(line.text) and line.text[0] not in " \t"
        if not line.fenced and STEP_LINE.match(line.text):
            current = _StepText([line])
            steps.append(current)
        elif at_column_zero and line.text.strip():
            current = None
        elif current is not None:
            current.lines.append(line)
    return steps


def step_count(body: str) -> int:
    """How many steps ``body`` has by the shared rule (P5), unbounded."""
    return len(_step_texts(body))


def _title(first_line: str) -> str:
    item = _STEP_PREFIX.sub("", first_line, count=1).strip()
    bold = _BOLD_TITLE.match(item)
    return clip((bold.group(1) if bold else item).strip(), MAX_STEP_TITLE_CHARS)


def _step(index: int, text: _StepText, *, agents: frozenset[str], skills: frozenset[str]) -> Step:
    prose = _prose(text.lines)
    named_agents = _named_agents(prose, agents)
    commands = _commands(prose)
    scripts = _scripts(prose)
    tags: list[StepTag] = []
    if STEP_PATTERNS["gate"].search(prose):
        tags.append("gate")
    if named_agents:
        tags.append("agent")
    if commands:
        tags.append("command")
    if scripts:
        tags.append("script")
    if STEP_PATTERNS["human"].search(prose):
        tags.append("human")
    return Step(
        index=index,
        title=_title(text.lines[0].text),
        tags=tuple(tags),
        agents=named_agents,
        skills=_named_skills(prose, skills),
        commands=commands,
        scripts=scripts,
    )


def _dynamic_context(body: str) -> int:
    count = 0
    for line in _lines(body):
        if line.dynamic_fence:
            count += 1
        elif not line.fenced:
            count += len(_DYNAMIC_SPAN.findall(line.text))
    return count


def derive_structure(
    body: str, *, agents: frozenset[str], skills: frozenset[str]
) -> SkillStructure:
    """``body``'s steps (at most ``MAX_STEPS``, titles cut to ``MAX_STEP_TITLE_CHARS``), with
    their S6 tags and the cataloged ``agents`` and ``skills`` they name, and the body's agents,
    skills, commands and gate titles (at most ``MAX_REFERENCES`` each)."""
    texts = _step_texts(body)
    steps = tuple(
        _step(index, text, agents=agents, skills=skills)
        for index, text in enumerate(texts[:MAX_STEPS], start=1)
    )
    prose = _prose(_lines(body))
    return SkillStructure(
        steps=steps,
        agents=_named_agents(prose, agents),
        skills=_named_skills(prose, skills),
        commands=_commands(prose),
        gates=tuple(step.title for step in steps if "gate" in step.tags),
        dynamic_context=_dynamic_context(body),
        truncated=len(texts) > MAX_STEPS,
    )
