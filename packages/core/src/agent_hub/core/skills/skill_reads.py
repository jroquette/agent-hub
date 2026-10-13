"""The Skills tab's reads use case: catalog, detail and bundled file of one hub (AGH-164, C2).

Each read lists the hub's skill roots (stat-only) and folds the files ``catalog_reads`` names,
read within the catalog's 16 MiB byte budget: a file that does not fit, and every one after it,
is left unread (``over_budget``); a file over its cap is never read. The fold is memoized per
hub and listing fingerprint (path, size, mtime and link target of every entry, ``hub.lock`` and
the settings files included), so a warm read is one listing walk plus the usage join. Items and
bundled files are found by id only: an id the fold did not issue is ``EntityNotFoundError``
(entity ``skill`` or ``skill file``) before anything is read.
"""

import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Final, Protocol

from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadHubFile
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_catalog import build_catalog, catalog_reads
from agent_hub.core.skills.skill_sources import (
    CATALOG_BUDGET_BYTES,
    MAX_SKILL_FILE_BYTES,
    MAX_SKILL_JSON_BYTES,
    CatalogInputs,
    FoldedCatalog,
    SkillSources,
)
from agent_hub.core.skills.skill_view import (
    FILE_ID,
    ITEM_NAME,
    BundledFile,
    BundledFileText,
    CatalogItem,
    ItemKind,
    SkillCatalog,
    SkillDetail,
    SkillFileTooLargeError,
    SkillUsage,
    Usage,
    item_id,
)

MEMO_ENTRIES: Final = 16
SKILL_ENTITY: Final = "skill"
SKILL_FILE_ENTITY: Final = "skill file"
_JSON_SUFFIX: Final = ".json"
_NAME: Final = re.compile(ITEM_NAME)
_FILE_ID: Final = re.compile(FILE_ID)
_ZERO: Final = Usage(count=0, user_count=0, model_count=0, last_used_at=None)

type _Fingerprint = tuple[bool, int, tuple[tuple[str, int, int, bool, str | None], ...]]


class SkillUsageSource(Protocol):
    """Where a project's skill and agent usage comes from (``EventReadModels.skill_usage``)."""

    def skill_usage(self, project: str) -> SkillUsage:
        """Usage by bare name over the window."""
        ...


def _fingerprint(sources: SkillSources) -> _Fingerprint:
    return (
        sources.truncated,
        sources.skipped,
        tuple(
            (entry.path, entry.size, entry.mtime_ns, entry.regular, entry.link_target)
            for entry in sources.files
        ),
    )


def _cap(path: str) -> int:
    return MAX_SKILL_JSON_BYTES if path.endswith(_JSON_SUFFIX) else MAX_SKILL_FILE_BYTES


def _over_cap(cap: int) -> UnreadHubFile:
    return UnreadHubFile(
        message=f"cannot read: over {cap} bytes", is_missing=False, kind="too_large"
    )


def _usage_of(item: CatalogItem, usage: SkillUsage | None) -> Usage | None:
    if item.kind is ItemKind.HOOK:
        return None
    if usage is None:
        return _ZERO
    found = usage.by_skill if item.kind is ItemKind.SKILL else usage.by_agent
    return found.get(item.name, _ZERO)


def _text_of(content: bytes) -> str | None:
    if b"\x00" in content:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


class SkillReads:
    """Catalog, detail and bundled file reads of a hub's skills (``HubReadModels.skill_*``).

    ``usage`` gives the 30-day counts joined by bare name; without it every count is zero.
    """

    def __init__(
        self,
        reader: HubFileReader,
        usage: SkillUsageSource | None = None,
        *,
        memo_entries: int = MEMO_ENTRIES,
    ) -> None:
        self._reader = reader
        self._usage = usage
        self._entries = memo_entries
        self._memo: OrderedDict[tuple[str, str, _Fingerprint], FoldedCatalog] = OrderedDict()
        self._guard = threading.Lock()

    def catalog(self, *, project: str, hub_path: str) -> SkillCatalog:
        """The hub's catalog with usage joined."""
        folded = self._folded(project, hub_path)
        usage = self._project_usage(project)
        items = tuple(
            item.model_copy(update={"usage": _usage_of(item, usage)})
            for item in folded.catalog.items
        )
        return folded.catalog.model_copy(update={"items": items})

    def detail(
        self, *, project: str, hub_path: str, kind: ItemKind, source: str, name: str
    ) -> SkillDetail:
        """One item by its id, with usage joined."""
        detail = self._detail(project, hub_path, kind=kind, source=source, name=name)[1]
        usage = _usage_of(detail, self._project_usage(project))
        return detail.model_copy(update={"usage": usage})

    def file(  # noqa: PLR0913 - the item's id and the file's id, all keyword-only
        self,
        *,
        project: str,
        hub_path: str,
        kind: ItemKind,
        source: str,
        name: str,
        file_id: str,
    ) -> BundledFileText:
        """One bundled file's text by its issued id; ``binary`` (NUL or not UTF-8) gives no
        text; over the per-file cap ``SkillFileTooLargeError``."""
        missing = EntityNotFoundError(
            entity=SKILL_FILE_ENTITY, entity_id=f"{item_id(kind, source, name)}/{file_id}"
        )
        if not _FILE_ID.match(file_id):
            raise missing
        folded, detail = self._detail(project, hub_path, kind=kind, source=source, name=name)
        path = folded.files.get(detail.id, {}).get(file_id)
        bundled = next((found for found in detail.files if found.id == file_id), None)
        if path is None or bundled is None or bundled.link:
            raise missing
        if bundled.too_large:
            raise SkillFileTooLargeError(limit=MAX_SKILL_FILE_BYTES, size=bundled.size)
        read = self._reader.read_skill_file(hub_path, path, max_bytes=MAX_SKILL_FILE_BYTES)
        if isinstance(read, UnreadHubFile):
            if read.kind == "too_large":
                size = max(bundled.size, MAX_SKILL_FILE_BYTES + 1)
                raise SkillFileTooLargeError(limit=MAX_SKILL_FILE_BYTES, size=size)
            raise missing
        return _bundled_text(bundled, read)

    def _project_usage(self, project: str) -> SkillUsage | None:
        return None if self._usage is None else self._usage.skill_usage(project)

    def _detail(
        self, project: str, hub_path: str, *, kind: ItemKind, source: str, name: str
    ) -> tuple[FoldedCatalog, SkillDetail]:
        wanted = item_id(kind, source, name)
        if not (_NAME.match(source) and _NAME.match(name)):
            raise EntityNotFoundError(entity=SKILL_ENTITY, entity_id=wanted)
        folded = self._folded(project, hub_path)
        detail = folded.details.get(wanted)
        if detail is None:
            raise EntityNotFoundError(entity=SKILL_ENTITY, entity_id=wanted)
        return folded, detail

    def _folded(self, project: str, hub_path: str) -> FoldedCatalog:
        sources = self._reader.skill_sources(hub_path)
        key = (hub_path, project, _fingerprint(sources))
        with self._guard:
            found = self._memo.get(key)
            if found is not None:
                self._memo.move_to_end(key)
                return found
        folded = build_catalog(self._inputs(project, hub_path, sources))
        with self._guard:
            self._memo[key] = folded
            self._memo.move_to_end(key)
            while len(self._memo) > self._entries:
                self._memo.popitem(last=False)
        return folded

    def _inputs(self, project: str, hub_path: str, sources: SkillSources) -> CatalogInputs:
        entries = {entry.path: entry for entry in sources.files}
        texts: dict[str, bytes | UnreadHubFile] = {}
        over_budget: set[str] = set()
        spent = 0
        for path in catalog_reads(sources):
            size, cap = entries[path].size, _cap(path)
            if size > cap:
                texts[path] = _over_cap(cap)
            elif over_budget or spent + size > CATALOG_BUDGET_BYTES:
                over_budget.add(path)
            else:
                read = self._reader.read_skill_file(hub_path, path, max_bytes=cap)
                spent += len(read) if isinstance(read, bytes) else 0
                texts[path] = read
        return CatalogInputs(
            project=project,
            project_plugin=project,
            sources=sources,
            texts=_frozen(texts),
            lock=self._reader.read_lock(hub_path),
            over_budget=frozenset(over_budget),
        )


def _frozen(texts: dict[str, bytes | UnreadHubFile]) -> Mapping[str, bytes | UnreadHubFile]:
    return dict(sorted(texts.items()))


def _bundled_text(bundled: BundledFile, content: bytes) -> BundledFileText:
    text = _text_of(content)
    return BundledFileText(
        id=bundled.id,
        path=bundled.path,
        role=bundled.role,
        size=len(content),
        text=text,
        binary=text is None,
    )
