"""The Skills tab's read models and item identity (AGH-164, L2, L5, P6).

An item is a skill (a folder holding ``SKILL.md``), an agent (a ``.md`` file) or a hook (one
entry of a settings or ``hooks.json`` file), addressed by ``kind/source/name``: ``source`` is the
folder it comes from (the plugin folder name, ``claude`` for a real entry in ``.claude/``,
``settings`` / ``settings-project`` for the two settings files' hooks). Every path a view holds
is hub-relative with ``/`` separators; no view ever holds an absolute path.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field

from agent_hub.core.errors import AgentHubError
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel

# A ``source`` or ``name`` segment: no dot, no slash, at most 128 characters (S3, L5).
ITEM_NAME: Final = r"^[A-Za-z0-9_-]{1,128}$"
# A bundled file's id: the first 16 hex digits of the sha256 of its hub-relative path (S7).
FILE_ID: Final = r"^[0-9a-f]{16}$"
# The usage window, in days back from the snapshot's ``now`` (S8, P2).
USAGE_DAYS: Final = 30
# What the catalog says of a third-party plugin: its content is never fetched (D1).
NOT_IN_HUB: Final = "not in this hub"


class ItemKind(StrEnum):
    """What an item is."""

    SKILL = "skill"
    AGENT = "agent"
    HOOK = "hook"


class Origin(StrEnum):
    """Who owns an item (S4): ``managed`` per ``hub.lock``, ``project-owned`` (any other plugin
    folder, ``settings.project.json``), ``local`` (a real entry in ``.claude/``)."""

    MANAGED = "managed"
    PROJECT_OWNED = "project-owned"
    LOCAL = "local"


class Mode(StrEnum):
    """Who can invoke a skill (S5, L2); ``neither`` reads "Hidden" in the UI."""

    USER_ONLY = "user-only"
    MODEL_ONLY = "model-only"
    BOTH = "both"
    NEITHER = "neither"


class DiagnosticSeverity(StrEnum):
    """How much a diagnostic matters; never blocking (D5)."""

    INFO = "info"
    WARNING = "warning"


class DiagnosticCode(StrEnum):
    """Every diagnostic an item can carry (P6)."""

    NAME_INVALID = "name_invalid"
    NAME_MISMATCH = "name_mismatch"
    DESCRIPTION_MISSING = "description_missing"
    DESCRIPTION_TOO_LONG = "description_too_long"
    FRONTMATTER_UNPARSEABLE = "frontmatter_unparseable"
    LINK_OUTSIDE_HUB = "link_outside_hub"
    TOO_LARGE = "too_large"
    NOT_REGULAR = "not_regular"
    NOT_TEXT = "not_text"
    BODY_TOO_LONG = "body_too_long"
    REFERENCE_NOT_FOUND = "reference_not_found"
    UNKNOWN_KEY = "unknown_key"
    DUPLICATE_NAME = "duplicate_name"
    NOT_LINKED = "not_linked"
    MODIFIED_SINCE_SYNC = "modified_since_sync"
    OVER_BUDGET = "over_budget"


_WARNINGS: Final = frozenset(
    {
        DiagnosticCode.NAME_INVALID,
        DiagnosticCode.NAME_MISMATCH,
        DiagnosticCode.DESCRIPTION_MISSING,
        DiagnosticCode.DESCRIPTION_TOO_LONG,
        DiagnosticCode.FRONTMATTER_UNPARSEABLE,
        DiagnosticCode.LINK_OUTSIDE_HUB,
        DiagnosticCode.TOO_LARGE,
        DiagnosticCode.NOT_REGULAR,
        DiagnosticCode.NOT_TEXT,
    }
)

# The one severity of each code (P6).
SEVERITY: Final[Mapping[DiagnosticCode, DiagnosticSeverity]] = {
    code: DiagnosticSeverity.WARNING if code in _WARNINGS else DiagnosticSeverity.INFO
    for code in DiagnosticCode
}

# The frontmatter keys Claude Code understands (S2); any other key is ``unknown_key`` (info).
KNOWN_SKILL_KEYS: Final = frozenset(
    {
        "name",
        "description",
        "when_to_use",
        "argument-hint",
        "arguments",
        "disable-model-invocation",
        "user-invocable",
        "allowed-tools",
        "disallowed-tools",
        "model",
        "effort",
        "context",
        "agent",
        "background",
        "hooks",
        "paths",
        "shell",
        "metadata",
        "license",
        "compatibility",
    }
)
KNOWN_AGENT_KEYS: Final = frozenset(
    {
        "name",
        "description",
        "tools",
        "disallowedTools",
        "model",
        "permissionMode",
        "maxTurns",
        "skills",
        "mcpServers",
        "hooks",
        "memory",
        "background",
        "effort",
        "isolation",
        "color",
        "initialPrompt",
    }
)

# A hook's state against ``settings.json`` (S4): a ``settings.project.json`` hook absent from it is
# ``not synced``.
type HookState = Literal["synced", "not synced"]
# A bundled file's role, from the first segment of its path in the skill folder (D4, S7).
type FileRole = Literal["scripts", "references", "assets", "other"]
# What a step of a skill's body does (S6).
type StepTag = Literal["gate", "agent", "command", "script", "human"]
# The type a step declares for itself with a leading backticked token, as the hub's workflow
# skills do ("`agent` **Scope**: ..."): who acts in it.
type StepType = Literal["agent", "script", "gate", "human"]
# A frontmatter value: a scalar, a list, or a one-level map of strings (L1, A4).
type SkillFrontmatterValue = str | tuple[str, ...] | dict[str, str]


def item_id(kind: ItemKind, source: str, name: str) -> str:
    """The stable id of an item (L5): ``<kind>/<source>/<name>``."""
    return f"{kind.value}/{source}/{name}"


def bare_name(raw: str) -> str:
    """A skill or agent name as usage counts it (S8): a leading ``/`` stripped, then any
    ``<plugin>:`` prefix (``/hub-workflow:feature`` -> ``feature``)."""
    name = raw.removeprefix("/")
    _, colon, rest = name.partition(":")
    return rest if colon else name


class Diagnostic(ViewModel):
    """One informational finding on an item, in one hub-relative line (D5, P6)."""

    code: DiagnosticCode
    severity: DiagnosticSeverity
    message: str


class Usage(ViewModel):
    """How often a skill or agent was used in the window: counts and a time only (D6, ADR 0019).

    ``user_count`` counts invocations typed by a person, ``model_count`` the ones the model made.
    """

    count: int = Field(ge=0)
    user_count: int = Field(ge=0)
    model_count: int = Field(ge=0)
    last_used_at: ApiTimestamp | None


class SkillUsage(ViewModel):
    """Usage per bare name over the window from ``since`` (S8, P2); ``truncated`` when more than
    500 names of a kind were seen (the most used are kept)."""

    since: ApiTimestamp
    by_skill: dict[str, Usage]
    by_agent: dict[str, Usage]
    truncated: bool = False


class CatalogItem(ViewModel):
    """One card of the catalog (D3, AC-164.7).

    ``description`` is the first line, at most 200 characters; ``invocation`` is
    ``/<name> <argument-hint>`` for a skill, None for an agent or a hook; ``mode`` is None for an
    agent or a hook; ``usage`` is None for a hook. ``linked_from`` lists the ``.claude/`` links
    that point at the item; ``active`` is false for a plugin hook whose plugin is not enabled;
    ``state`` is set for hooks only.
    """

    id: str
    kind: ItemKind
    source: str
    name: str
    description: str | None
    origin: Origin
    mode: Mode | None
    invocation: str | None
    source_path: str
    diagnostics_count: int = Field(ge=0)
    usage: Usage | None
    linked_from: tuple[str, ...] = ()
    active: bool = True
    state: HookState | None = None


class ExternalPlugin(ViewModel):
    """A third-party plugin named by ``enabledPlugins`` or the marketplace (D1, P7); its content
    is not in the hub and is never fetched. ``pin`` is the pinned sha or ref, or None."""

    name: str
    marketplace: str | None
    pin: str | None
    enabled: bool
    content: Literal["not in this hub"] = NOT_IN_HUB


class SkillCatalog(ViewModel):
    """A project's skills, agents and hooks in stable order (kind, name, source).

    ``truncated`` says a bound stopped the listing or the reads; ``notice`` is one line for the
    owner (an empty hub, a file not read), or None.
    """

    project: str
    items: tuple[CatalogItem, ...]
    external_plugins: tuple[ExternalPlugin, ...] = ()
    truncated: bool = False
    notice: str | None = None
    usage_days: int = USAGE_DAYS


class FrontmatterPair(ViewModel):
    """One frontmatter key in file order; ``known`` when Claude Code understands the key."""

    key: str
    value: SkillFrontmatterValue
    known: bool = False


class TocEntry(ViewModel):
    """One heading of a body (outside fenced code); the web computes its anchor (P5)."""

    level: int = Field(ge=1, le=6)
    text: str


class Step(ViewModel):
    """One top-level ordered list item of a body (S6); ``index`` is 1-based, as ``#step-<n>``.

    ``declared_type`` is the type the step states itself, when it starts with one; ``summary`` is
    the rest of its first line as plain text (Markdown marks dropped), empty when there is none.
    """

    index: int = Field(ge=1)
    title: str
    declared_type: StepType | None = None
    summary: str = ""
    tags: tuple[StepTag, ...] = ()
    agents: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()


class SkillStructure(ViewModel):
    """What the body's text says it does, derived heuristically (S6): labelled so in the UI.

    ``dynamic_context`` counts the ``!`…``` and ```` ```! ```` blocks that run at invocation (shown
    as text, never run); ``truncated`` when steps past the bound were dropped.
    """

    steps: tuple[Step, ...] = ()
    agents: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    gates: tuple[str, ...] = ()
    dynamic_context: int = Field(default=0, ge=0)
    truncated: bool = False


class Relation(ViewModel):
    """A link to another item of the catalog (Uses / Used by)."""

    id: str
    kind: ItemKind
    source: str
    name: str


class BundledFile(ViewModel):
    """A file of a skill folder other than ``SKILL.md`` (S7): ``path`` is relative to the skill
    folder, ``id`` server-issued; ``link`` when it is a link (never read), ``too_large`` when over
    the per-file cap."""

    id: str
    path: str
    role: FileRole
    size: int = Field(ge=0)
    link: bool = False
    too_large: bool = False


class ContextCost(ViewModel):
    """Approximate tokens (characters / 4, P8): ``always_loaded_tokens`` from the description (0
    when the model cannot invoke the skill), ``on_invoke_tokens`` from the body."""

    always_loaded_tokens: int = Field(ge=0)
    on_invoke_tokens: int = Field(ge=0)
    approximate: Literal[True] = True


class HookFacts(ViewModel):
    """A hook as configured (D4): ``command`` is inert text, never run."""

    event: str
    matcher: str | None
    type: str
    command: str | None
    timeout: int | None
    active: bool
    state: HookState


class LockFacts(ViewModel):
    """What ``hub.lock`` says of the item's file: its ownership and, when managed, its sha256."""

    ownership: str
    sha256: str | None


class SkillDetail(CatalogItem):
    """One item's detail page (D4, AC-164.8): the card's fields and what the file says.

    ``body`` is the text after the frontmatter and ``raw`` the whole file decoded as UTF-8; both
    are None when the file was not read (too large, not regular, not text, over budget). A hook
    has ``hook`` set and no body, structure or cost.
    """

    description_full: str | None = None
    when_to_use: str | None = None
    argument_hint: str | None = None
    allowed_tools: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    model: str | None = None
    lock: LockFacts | None = None
    frontmatter: tuple[FrontmatterPair, ...] = ()
    body: str | None = None
    raw: str | None = None
    toc: tuple[TocEntry, ...] = ()
    structure: SkillStructure | None = None
    uses: tuple[Relation, ...] = ()
    used_by: tuple[Relation, ...] = ()
    files: tuple[BundledFile, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    context_cost: ContextCost | None = None
    hook: HookFacts | None = None


class BundledFileText(ViewModel):
    """A bundled file's text, inert (S7); ``binary`` (NUL or not UTF-8) gives no text."""

    id: str
    path: str
    role: FileRole
    size: int = Field(ge=0)
    text: str | None
    binary: bool = False


class SkillDocument(ViewModel):
    """A ``SKILL.md`` or agent file split by the skills reader (L1): ordered ``pairs``, the body
    after the closing fence, and ``problem`` (one line) when the frontmatter is unparseable,
    then ``pairs`` is empty and ``body`` is the whole text."""

    pairs: tuple[FrontmatterPair, ...] = ()
    body: str
    problem: str | None = None


class SkillFileTooLargeError(AgentHubError):
    """A bundled file is larger than ``limit`` bytes (answers 413)."""

    def __init__(self, *, limit: int, size: int) -> None:
        self.limit = limit
        self.size = size
        super().__init__(f"skill file is {size} bytes, over the {limit}-byte limit")
