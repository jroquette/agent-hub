"""Bring a hub's knowledge rows up to date with its checkout, then search them (AGH-391,
ADR 0044: D-sync, D-reindex, D-version, D-skipreport, AM-1).

``KnowledgeCheckout`` is the port the composition roots implement over the hub's checkout (the
git listing and the reads); ``sync_knowledge`` lists, plans (``plan_sync``), reads only what the
plan names, and writes the result to the ``KnowledgeIndex`` in one ``apply``, made only when
something changed, so a search over an unchanged hub reads and writes nothing.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from agent_hub.core.errors import AgentHubError
from agent_hub.core.knowledge import document_rules
from agent_hub.core.knowledge.document_rules import UNREADABLE, document_from
from agent_hub.core.knowledge.knowledge_index import (
    INDEX_VERSION,
    Fingerprint,
    IndexChange,
    IndexedDocument,
    Kind,
    KnowledgeIndex,
    SearchHit,
    SkippedFile,
    StoredFile,
    StoredIndex,
)
from agent_hub.core.knowledge.search_query import MAX_RESULTS
from agent_hub.core.knowledge.sync_plan import FileToRead, ListedFile, plan_sync

_NO_ROWS: Final = StoredIndex(version=None, files={})


class KnowledgeCheckoutError(AgentHubError):
    """The hub's sources cannot be listed: git missing or failing on a folder, or a listing
    over its bounds (AM-1). The message names the folder or the count, never a file's text."""


class KnowledgeCheckout(Protocol):
    """The Markdown files under a hub's sources (its ``brain/`` minus ``brain/auto/``, each
    repo's ``docs/``), as the index sees them."""

    def listed(self) -> tuple[ListedFile, ...]:
        """Every file the index looks at, by hub-relative path, sorted, each once;
        ``KnowledgeCheckoutError`` when a source cannot be listed."""
        ...

    def read(self, path: str) -> bytes | str | None:
        """The bytes of the listed file at ``path`` (at most ``MAX_DOCUMENT_BYTES + 1``), the
        reason it is skipped when it cannot be read as a regular file, or None when it is gone."""
        ...


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SyncReport(_Frozen):
    """What a sync did: files listed, read, indexed (new text written) and rows dropped, and
    the files reported as skipped, by path."""

    listed: int
    read: int
    indexed: int
    dropped: int
    skipped: tuple[SkippedFile, ...]


class SearchOutcome(_Frozen):
    """A search's results and the report of the sync that ran first."""

    results: tuple[SearchHit, ...]
    report: SyncReport


@dataclass
class _Reads:
    """What reading the planned files gave, to write in one change."""

    documents: list[IndexedDocument] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)
    touched: dict[str, Fingerprint] = field(default_factory=dict)
    vanished: list[str] = field(default_factory=list)


def sync_knowledge(
    index: KnowledgeIndex, checkout: KnowledgeCheckout, hub: str, *, rebuild: bool = False
) -> SyncReport:
    """Bring the hub's rows up to date with ``checkout``; with ``rebuild`` (``hub brain
    reindex``) drop them and read every listed file. ``KnowledgeCheckoutError`` before any read
    when the listing holds more than ``MAX_LISTED_FILES`` files."""
    listing = checkout.listed()
    cap = document_rules.MAX_LISTED_FILES
    if len(listing) > cap:
        msg = f"{len(listing)} Markdown files under the hub's sources, more than {cap}; "
        raise KnowledgeCheckoutError(msg + "nothing was indexed")
    stored = _NO_ROWS if rebuild else index.stored(hub)
    plan = plan_sync(stored, listing, version=INDEX_VERSION)
    reads = _read(checkout, plan.to_read, _NO_ROWS.files if plan.rebuild else stored.files)
    change = IndexChange(
        version=INDEX_VERSION,
        rebuild=rebuild or plan.rebuild,
        documents=tuple(reads.documents),
        skipped=plan.skipped_now + tuple(reads.skipped),
        touched=reads.touched,
        dropped=plan.dropped + tuple(reads.vanished),
    )
    if not change.is_empty:
        index.apply(hub, change)
    return SyncReport(
        listed=len(listing),
        read=len(plan.to_read),
        indexed=len(change.documents),
        dropped=len(change.dropped),
        skipped=tuple(sorted(change.skipped, key=lambda skipped: skipped.path)),
    )


def search_knowledge(
    index: KnowledgeIndex,
    checkout: KnowledgeCheckout,
    hub: str,
    *,
    words: tuple[str, ...],
    kinds: tuple[Kind, ...] = (),
) -> SearchOutcome:
    """Sync the hub's rows (``sync_knowledge``), then search them for every word of ``words``,
    of ``kinds`` when not empty, at most ``MAX_RESULTS``."""
    report = sync_knowledge(index, checkout, hub)
    results = index.search(hub, words, kinds=kinds, limit=MAX_RESULTS) if words else ()
    return SearchOutcome(results=results, report=report)


def _read(
    checkout: KnowledgeCheckout, files: tuple[FileToRead, ...], rows: Mapping[str, StoredFile]
) -> _Reads:
    """Read each planned file: a file gone since the listing loses its row; a read that fails
    is reported every time (nothing remembers it); a text whose hash the row already holds only
    moves the row's fingerprint."""
    reads = _Reads()
    for file in files:
        content = checkout.read(file.path)
        if content is None:
            if file.path in rows:
                reads.vanished.append(file.path)
        elif isinstance(content, str):
            fingerprint = None if content == UNREADABLE else file.fingerprint
            reads.skipped.append(
                SkippedFile(path=file.path, fingerprint=fingerprint, reason=content)
            )
        else:
            _add_read(reads, file, content, row=rows.get(file.path))
    return reads


def _add_read(reads: _Reads, file: FileToRead, data: bytes, *, row: StoredFile | None) -> None:
    result = document_from(file.path, data, file.fingerprint)
    if isinstance(result, SkippedFile):
        reads.skipped.append(result)
    elif row is not None and row.sha256 == result.sha256:
        reads.touched[file.path] = file.fingerprint
    else:
        reads.documents.append(result)
