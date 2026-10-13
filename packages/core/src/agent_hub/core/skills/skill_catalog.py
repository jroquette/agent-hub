"""The catalog fold: a hub's skill listing and the files read for it, as items (AGH-164, C1).

``build_catalog`` is pure: the same ``CatalogInputs`` give the same ``FoldedCatalog``, whatever
the order of the listing or of the texts. Items come from the listing (skill folders holding a
``SKILL.md``, agent ``.md`` files, the hooks of the settings files and of each plugin's
``hooks.json``), addressed by ``kind/source/name`` (L5): ``source`` is the plugin folder,
``claude`` for a real entry in ``.claude/``, ``settings`` / ``settings-project`` for the settings
hooks. A link is never followed: a ``.claude/`` link whose target, resolved lexically, is a
cataloged item becomes that item's ``linked_from``; any other link is an item of its own with
``link_outside_hub`` and no target text. A file that was not read (too large, not regular, not
text, over the catalog's byte budget) leaves its item listed with a diagnostic and no body.
``catalog_reads`` names the files the reads use case reads for the fold, in the order the byte
budget is spent.
"""

import posixpath
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Final

from agent_hub.core.doctor.snapshot import LockState
from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry, ManagedLinkEntry
from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.redaction.redact import clip
from agent_hub.core.skills.external_plugins import (
    enabled_plugins,
    external_plugins,
    marketplace_name,
)
from agent_hub.core.skills.skill_frontmatter import read_skill_document
from agent_hub.core.skills.skill_hooks import HookRecord, HubJsonContent, hook_records
from agent_hub.core.skills.skill_sources import (
    AGENT_SUFFIX,
    AGENTS_FOLDER,
    BASE_PLUGIN,
    CATALOG_BUDGET_BYTES,
    CLAUDE_FOLDER,
    CLAUDE_SOURCE,
    HOOKS_FILE,
    HOOKS_FOLDER,
    MARKETPLACE_PATH,
    MAX_SKILL_FILE_BYTES,
    PLUGIN_FOLDER,
    PROJECT_SETTINGS_PATH,
    RESERVED_SOURCES,
    SETTINGS_PATH,
    SKILL_FILE,
    SKILLS_FOLDER,
    CatalogInputs,
    FoldedCatalog,
    SkillSources,
    SourceFile,
)
from agent_hub.core.skills.skill_view import (
    ITEM_NAME,
    KNOWN_AGENT_KEYS,
    KNOWN_SKILL_KEYS,
    SEVERITY,
    CatalogItem,
    Diagnostic,
    DiagnosticCode,
    ExternalPlugin,
    ItemKind,
    LockFacts,
    Mode,
    Origin,
    SkillCatalog,
    SkillDetail,
    SkillDocument,
    SkillFrontmatterValue,
    Usage,
    item_id,
)

EMPTY_NOTICE: Final = "No skills found in this hub; it may not be synced yet."
LOCK_UNREAD_NOTICE: Final = "hub.lock not read: origins from folder names"
MAX_CARD_DESCRIPTION_CHARS: Final = 200
# The JSON files the fold reads besides the items' own files, in budget order.
JSON_FILES: Final = (SETTINGS_PATH, PROJECT_SETTINGS_PATH, MARKETPLACE_PATH)

_NAME: Final = re.compile(ITEM_NAME)
_KIND_ORDER: Final = {kind: index for index, kind in enumerate(ItemKind)}
_ZERO_USAGE: Final = Usage(count=0, user_count=0, model_count=0, last_used_at=None)
_TRUE: Final = "true"
_FALSE: Final = "false"
_LINK_OUTSIDE: Final = "link not followed: its target is outside the hub or not an item here"
_CLAUDE_ITEM_SEGMENTS: Final = 3
_PLUGIN_ITEM_SEGMENTS: Final = 4


@dataclass(slots=True)
class _Folder:
    """A skill folder of the listing: its ``SKILL.md`` entry, the other entries below it, and
    the entry of the folder itself when it is a link (then nothing below it is listed)."""

    source: str
    name: str
    root: str
    skill_md: SourceFile | None = None
    files: list[SourceFile] = field(default_factory=list)
    link: SourceFile | None = None

    @property
    def skill_path(self) -> str:
        return f"{self.root}/{SKILL_FILE}"


@dataclass(frozen=True, slots=True)
class _AgentFile:
    """An agent file of the listing, or any item root that is a link."""

    source: str
    name: str
    entry: SourceFile


@dataclass(slots=True)
class _Listing:
    """The listing sorted into skill folders, agent files, plugin ``hooks.json`` entries and
    the single files, with the plugin folders seen and the notices of what was skipped."""

    folders: dict[tuple[str, str], _Folder] = field(default_factory=dict)
    agents: dict[tuple[str, str], _AgentFile] = field(default_factory=dict)
    hooks: dict[str, SourceFile] = field(default_factory=dict)
    singles: dict[str, SourceFile] = field(default_factory=dict)
    plugins: set[str] = field(default_factory=set)
    skipped_plugins: set[str] = field(default_factory=set)
    skipped_names: int = 0

    def add(self, entry: SourceFile) -> None:
        segments = entry.path.split("/")
        if segments[0] == CLAUDE_FOLDER and len(segments) >= _CLAUDE_ITEM_SEGMENTS:
            self._item(entry, source=CLAUDE_SOURCE, segments=segments, root_at=2)
        elif segments[0] == PLUGIN_FOLDER and len(segments) >= _PLUGIN_ITEM_SEGMENTS:
            plugin = segments[1]
            if plugin in RESERVED_SOURCES or not _NAME.match(plugin):
                self.skipped_plugins.add(plugin)
                return
            self.plugins.add(plugin)
            if segments[2:] == [HOOKS_FOLDER, HOOKS_FILE]:
                self.hooks[plugin] = entry
            else:
                self._item(entry, source=plugin, segments=segments, root_at=3)
        else:
            self.singles[entry.path] = entry

    def _item(self, entry: SourceFile, *, source: str, segments: list[str], root_at: int) -> None:
        folder, rest = segments[root_at - 1], segments[root_at:]
        if folder == SKILLS_FOLDER:
            self._skill(entry, source, rest, root="/".join(entry.path.split("/")[: root_at + 1]))
        elif folder == AGENTS_FOLDER and len(rest) == 1:
            name = rest[0].removesuffix(AGENT_SUFFIX)
            if not _NAME.match(name):
                self.skipped_names += 1
                return
            self.agents[(source, name)] = _AgentFile(source=source, name=name, entry=entry)

    def _skill(self, entry: SourceFile, source: str, rest: list[str], *, root: str) -> None:
        name = rest[0]
        if not _NAME.match(name):
            self.skipped_names += 1
            return
        folder = self.folders.setdefault((source, name), _Folder(source, name, root))
        if len(rest) == 1:
            folder.link = entry if entry.link_target is not None else folder.link
        elif rest[1:] == [SKILL_FILE]:
            folder.skill_md = entry
        else:
            folder.files.append(entry)


def _listing(sources: SkillSources) -> _Listing:
    listing = _Listing()
    for entry in sorted(sources.files, key=lambda found: found.path):
        listing.add(entry)
    for folder in listing.folders.values():
        folder.files.sort(key=lambda found: found.path)
    return listing


def _readable_folders(listing: _Listing) -> Iterator[_Folder]:
    for folder in listing.folders.values():
        if folder.link is None and folder.skill_md is not None and folder.skill_md.regular:
            yield folder


def catalog_reads(sources: SkillSources) -> tuple[str, ...]:
    """The hub-relative paths the fold reads, in the order the byte budget is spent: the
    settings files and the marketplace, then every regular ``SKILL.md``, agent file and plugin
    ``hooks.json`` by path. ``hub.lock`` is read on its own (``read_lock``)."""
    listing = _listing(sources)
    singles = tuple(
        path for path in JSON_FILES if path in listing.singles and listing.singles[path].regular
    )
    items = [folder.skill_path for folder in _readable_folders(listing)]
    items.extend(agent.entry.path for agent in listing.agents.values() if agent.entry.regular)
    items.extend(entry.path for entry in listing.hooks.values() if entry.regular)
    return singles + tuple(sorted(items))


# Links


def resolve_link(link_path: str, target: str) -> str | None:
    """The hub-relative path a link at ``link_path`` names, resolved lexically (never on the
    disk); None when the target is empty, absolute or leaves the hub."""
    if not target or target.startswith("/") or "\\" in target:
        return None
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(link_path), target))
    if resolved in {".", ".."} or resolved.startswith("../"):
        return None
    return resolved


# Reads


@dataclass(frozen=True, slots=True)
class _Read:
    """An item file as read: its text and bytes, or the diagnostic that says why not."""

    text: str | None = None
    raw: bytes | None = None
    problem: Diagnostic | None = None


def _diagnostic(code: DiagnosticCode, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=SEVERITY[code], message=message)


def _decoded(content: bytes) -> _Read:
    if b"\x00" in content:
        return _Read(problem=_diagnostic(DiagnosticCode.NOT_TEXT, "file not read: not text"))
    try:
        return _Read(text=content.decode("utf-8"), raw=content)
    except UnicodeDecodeError:
        return _Read(problem=_diagnostic(DiagnosticCode.NOT_TEXT, "file not read: not UTF-8"))


def _too_large(size: int) -> Diagnostic:
    return _diagnostic(
        DiagnosticCode.TOO_LARGE,
        f"file not read: {size} bytes, over the {MAX_SKILL_FILE_BYTES}-byte limit",
    )


class _Texts:
    """What the reads gave for each path, and why a path has no text."""

    def __init__(self, inputs: CatalogInputs) -> None:
        self._texts = inputs.texts
        self._over_budget = inputs.over_budget

    def item(self, entry: SourceFile) -> _Read:
        if entry.link_target is not None:
            code = DiagnosticCode.LINK_OUTSIDE_HUB
            return _Read(problem=_diagnostic(code, f"{SKILL_FILE} is a link; {_LINK_OUTSIDE}"))
        if not entry.regular:
            message = "file not read: not a regular file"
            return _Read(problem=_diagnostic(DiagnosticCode.NOT_REGULAR, message))
        if entry.path in self._over_budget:
            message = f"file not read: the catalog's {CATALOG_BUDGET_BYTES}-byte budget ran out"
            return _Read(problem=_diagnostic(DiagnosticCode.OVER_BUDGET, message))
        content = self._texts.get(entry.path)
        if isinstance(content, bytes):
            if len(content) > MAX_SKILL_FILE_BYTES:
                return _Read(problem=_too_large(len(content)))
            return _decoded(content)
        if (content is None and entry.size > MAX_SKILL_FILE_BYTES) or (
            content is not None and content.kind == "too_large"
        ):
            return _Read(problem=_too_large(entry.size))
        message = "file not read" if content is None else f"file not read ({content.message})"
        return _Read(problem=_diagnostic(DiagnosticCode.NOT_REGULAR, message))

    def json(self, entry: SourceFile | None) -> HubJsonContent:
        if entry is None:
            return None
        if entry.path in self._over_budget:
            return UnreadHubFile(message="over the catalog's byte budget", is_missing=False)
        content = self._texts.get(entry.path)
        if content is not None:
            return content
        reason = "not a regular file" if not entry.regular else "not read"
        return UnreadHubFile(message=reason, is_missing=False)


# Frontmatter facts


def _value_text(value: SkillFrontmatterValue | None) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        return ", ".join(value)
    return None


def _tool_list(value: SkillFrontmatterValue | None) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(part.strip() for part in value if part.strip())
    if not isinstance(value, str):
        return ()
    parts = value.split(",") if "," in value or "(" in value else value.split()
    return tuple(part.strip() for part in parts if part.strip())


def _flag(value: SkillFrontmatterValue | None) -> str | None:
    text = _value_text(value)
    return None if text is None else text.strip().lower()


def _mode(values: Mapping[str, SkillFrontmatterValue]) -> Mode:
    user_only = _flag(values.get("disable-model-invocation")) == _TRUE
    model_only = _flag(values.get("user-invocable")) == _FALSE
    if user_only and model_only:
        return Mode.NEITHER
    if user_only:
        return Mode.USER_ONLY
    return Mode.MODEL_ONLY if model_only else Mode.BOTH


def _first_line(text: str | None) -> str | None:
    if text is None or not text.strip():
        return None
    return clip(text.strip().splitlines()[0].strip(), MAX_CARD_DESCRIPTION_CHARS)


# Origins and hub.lock


class _Lock:
    """``hub.lock`` when it was read, for origins and ownership facts."""

    def __init__(self, state: LockState | None) -> None:
        self.lock = state if isinstance(state, HubLock) else None

    def facts(self, path: str) -> LockFacts | None:
        entry = None if self.lock is None else self.lock.files.get(path)
        if entry is None:
            return None
        sha = entry.sha256 if isinstance(entry, ManagedFileEntry) else None
        return LockFacts(ownership=entry.ownership, sha256=sha)

    def managed(self, path: str) -> bool:
        if self.lock is None:
            return False
        entry = self.lock.files.get(path)
        return isinstance(entry, ManagedFileEntry | ManagedLinkEntry)

    def origin(self, source: str, path: str) -> Origin:
        managed = source == BASE_PLUGIN if self.lock is None else self.managed(path)
        if managed:
            return Origin.MANAGED
        return Origin.LOCAL if source == CLAUDE_SOURCE else Origin.PROJECT_OWNED


# Items


@dataclass(slots=True)
class _Item:
    """One item while the fold builds it."""

    kind: ItemKind
    source: str
    name: str
    source_path: str
    origin: Origin
    read: _Read = field(default_factory=_Read)
    document: SkillDocument | None = None
    folder: _Folder | None = None
    lock: LockFacts | None = None
    linked_from: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    hook: HookRecord | None = None

    @property
    def id(self) -> str:
        return item_id(self.kind, self.source, self.name)

    def values(self) -> dict[str, SkillFrontmatterValue]:
        if self.document is None:
            return {}
        return {pair.key: pair.value for pair in self.document.pairs}


def _document(item: _Item) -> None:
    if item.read.problem is not None:
        item.diagnostics.append(item.read.problem)
        return
    if item.read.text is not None:
        known = KNOWN_SKILL_KEYS if item.kind is ItemKind.SKILL else KNOWN_AGENT_KEYS
        item.document = read_skill_document(item.read.text, known_keys=known)


class _Fold:
    def __init__(self, inputs: CatalogInputs) -> None:
        self.inputs = inputs
        self.listing = _listing(inputs.sources)
        self.texts = _Texts(inputs)
        self.lock = _Lock(inputs.lock)
        self.items: dict[str, _Item] = {}
        self.notices: list[str] = []
        self.truncated = inputs.sources.truncated or bool(inputs.over_budget)
        self.external: tuple[ExternalPlugin, ...] = ()

    def run(self) -> None:
        links: list[tuple[ItemKind, _AgentFile]] = []
        for folder in self.listing.folders.values():
            if folder.link is not None:
                links.append((ItemKind.SKILL, _AgentFile(folder.source, folder.name, folder.link)))
            elif folder.skill_md is not None:
                self._skill(folder, folder.skill_md)
        for agent in self.listing.agents.values():
            if agent.entry.link_target is not None:
                links.append((ItemKind.AGENT, agent))
            else:
                self._agent(agent)
        for kind, link in links:
            self._link(kind, link)
        self._hooks()

    def _add(self, item: _Item) -> _Item:
        self.items[item.id] = item
        return item

    def _skill(self, folder: _Folder, skill_md: SourceFile) -> None:
        path = folder.skill_path
        item = self._add(
            _Item(
                kind=ItemKind.SKILL,
                source=folder.source,
                name=folder.name,
                source_path=path,
                origin=self.lock.origin(folder.source, path),
                read=self.texts.item(skill_md),
                folder=folder,
                lock=self.lock.facts(path),
            )
        )
        _document(item)

    def _agent(self, agent: _AgentFile) -> None:
        path = agent.entry.path
        item = self._add(
            _Item(
                kind=ItemKind.AGENT,
                source=agent.source,
                name=agent.name,
                source_path=path,
                origin=self.lock.origin(agent.source, path),
                read=self.texts.item(agent.entry),
                lock=self.lock.facts(path),
            )
        )
        _document(item)

    def _target(self, kind: ItemKind, resolved: str | None) -> _Item | None:
        if resolved is None:
            return None
        for item in self.items.values():
            if item.kind is not kind:
                continue
            root = item.folder.root if item.folder is not None else item.source_path
            if root == resolved:
                return item
        return None

    def _link(self, kind: ItemKind, link: _AgentFile) -> None:
        source, name, entry = link.source, link.name, link.entry
        target = self._target(kind, resolve_link(entry.path, entry.link_target or ""))
        if target is not None:
            target.linked_from.append(entry.path)
            return
        problem = _diagnostic(DiagnosticCode.LINK_OUTSIDE_HUB, _LINK_OUTSIDE)
        self._add(
            _Item(
                kind=kind,
                source=source,
                name=name,
                source_path=entry.path,
                origin=self.lock.origin(source, entry.path),
                diagnostics=[problem],
                lock=self.lock.facts(entry.path),
            )
        )

    def _hooks(self) -> None:
        singles = self.listing.singles
        settings = self.texts.json(singles.get(SETTINGS_PATH))
        marketplace = self.texts.json(singles.get(MARKETPLACE_PATH))
        plugin_hooks = {
            plugin: self.texts.json(entry) for plugin, entry in self.listing.hooks.items()
        }
        fold = hook_records(
            settings,
            self.texts.json(singles.get(PROJECT_SETTINGS_PATH)),
            plugin_hooks,
            enabled=enabled_plugins(settings),
            marketplace=marketplace_name(marketplace),
        )
        self.notices.extend(fold.notices)
        self.truncated = self.truncated or fold.truncated
        for record in fold.records:
            self._add(
                _Item(
                    kind=ItemKind.HOOK,
                    source=record.source,
                    name=record.name,
                    source_path=record.source_path,
                    origin=self._hook_origin(record),
                    hook=record,
                    lock=self.lock.facts(record.source_path),
                )
            )
        found = external_plugins(
            marketplace, settings, local_plugins=frozenset(self.listing.plugins)
        )
        self.notices.extend(found.notices)
        self.external = found.plugins

    def _hook_origin(self, record: HookRecord) -> Origin:
        if record.source in self.listing.hooks and self.lock.lock is not None:
            return self.lock.origin(record.source, record.source_path)
        return record.origin

    def catalog_notices(self) -> list[str]:
        notices = list(self.notices)
        if self.listing.skipped_plugins:
            names = ", ".join(f"{PLUGIN_FOLDER}/{p}" for p in sorted(self.listing.skipped_plugins))
            notices.append(f"{names}: skipped (a reserved or unaddressable folder name)")
        if self.listing.skipped_names:
            notices.append(
                f"{self.listing.skipped_names} entries skipped: names outside letters, digits,"
                " '-' and '_'"
            )
        if self.inputs.sources.truncated:
            notices.append(
                f"the listing stopped at a bound: {self.inputs.sources.skipped} entries not listed"
            )
        if self.inputs.over_budget:
            notices.append(
                f"{len(self.inputs.over_budget)} files not read: the catalog's"
                f" {CATALOG_BUDGET_BYTES}-byte budget ran out"
            )
        if not self.items:
            return [EMPTY_NOTICE, *notices]
        if self.lock.lock is None:
            notices.append(LOCK_UNREAD_NOTICE)
        return notices


# Views


def _detail(item: _Item) -> SkillDetail:
    values = item.values()
    description = _value_text(values.get("description"))
    if item.hook is not None:
        description = _hook_description(item.hook)
    is_skill = item.kind is ItemKind.SKILL
    hint = _value_text(values.get("argument-hint"))
    invocation = None
    if is_skill:
        invocation = f"/{item.name}" if not hint else f"/{item.name} {hint}"
    document = item.document
    return SkillDetail(
        id=item.id,
        kind=item.kind,
        source=item.source,
        name=item.name,
        description=_first_line(description),
        origin=item.origin,
        mode=_mode(values) if is_skill else None,
        invocation=invocation,
        source_path=item.source_path,
        diagnostics_count=len(item.diagnostics),
        usage=None if item.kind is ItemKind.HOOK else _ZERO_USAGE,
        linked_from=tuple(sorted(item.linked_from)),
        active=True if item.hook is None else item.hook.facts.active,
        state=None if item.hook is None else item.hook.facts.state,
        description_full=description,
        when_to_use=_value_text(values.get("when_to_use")),
        argument_hint=hint,
        allowed_tools=_tool_list(values.get("allowed-tools")),
        tools=_tool_list(values.get("tools")),
        model=_value_text(values.get("model")),
        lock=item.lock,
        frontmatter=() if document is None else document.pairs,
        body=None if document is None else document.body,
        raw=item.read.text,
        diagnostics=tuple(item.diagnostics),
        hook=None if item.hook is None else item.hook.facts,
    )


def _hook_description(record: HookRecord) -> str:
    facts = record.facts
    matcher = f" ({facts.matcher})" if facts.matcher else ""
    command = f": {facts.command}" if facts.command else ""
    return f"{facts.event}{matcher}{command}"


def _card(detail: SkillDetail) -> CatalogItem:
    return CatalogItem.model_validate(
        {name: getattr(detail, name) for name in CatalogItem.model_fields}
    )


def _order(detail: SkillDetail) -> tuple[int, str, str]:
    return (_KIND_ORDER[detail.kind], detail.name, detail.source)


def _sorted(details: Iterable[SkillDetail]) -> list[SkillDetail]:
    return sorted(details, key=_order)


def build_catalog(inputs: CatalogInputs) -> FoldedCatalog:
    """The catalog of ``inputs`` without usage (zero for skills and agents, None for hooks),
    each item's detail by id, and each skill's bundled files by file id."""
    fold = _Fold(inputs)
    fold.run()
    details = _sorted(_detail(item) for item in fold.items.values())
    notices = fold.catalog_notices()
    catalog = SkillCatalog(
        project=inputs.project,
        items=tuple(_card(detail) for detail in details),
        external_plugins=fold.external,
        truncated=fold.truncated,
        notice="; ".join(notices) if notices else None,
    )
    return FoldedCatalog(catalog=catalog, details={detail.id: detail for detail in details})
