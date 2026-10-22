"""The app's knowledge reads: a project's hub searched, and the documents linking to one of its
notes (AGH-393, D-search-route, D-backlinks-route, P-9).

``ReadKnowledge`` resolves the project through ``HubReadModels`` (``get_project``'s registered
hub path, ``project_repos``' folders), builds the hub's ``KnowledgeSources`` with ``sources``
and runs AGH-391's ``search_knowledge`` or ``backlinks_knowledge`` on the index ``index`` opens,
so each read syncs the hub's rows first. The rows are keyed by the registered hub's path (AM-6).
A backlinks path is checked as the note route checks it (``readable_note_path``, AM-3) before
anything is read. A repo that is not checked out is a warning of the search, never an error.

The answer models are named apart from the global search's ``SearchHit`` (P-9): FastAPI would
otherwise rename both in the OpenAPI document.
"""

from collections.abc import Callable
from typing import Protocol

from pydantic import Field

from agent_hub.core.brain.brain_path import BRAIN_FOLDER, readable_note_path
from agent_hub.core.knowledge.knowledge_index import Kind, KnowledgeIndex, SearchHit
from agent_hub.core.knowledge.search_query import MAX_RESULTS, query_words
from agent_hub.core.knowledge.sync_knowledge import (
    KnowledgeCheckout,
    SyncReport,
    backlinks_knowledge,
    search_knowledge,
)
from agent_hub.core.readmodels.read_ports import HubReadModels
from agent_hub.core.readmodels.view_types import ViewModel


class KnowledgeSources(KnowledgeCheckout, Protocol):
    """A hub's checkout as the index sees it, naming the repos it could not find."""

    def not_checked_out(self) -> tuple[str, ...]:
        """The repo folders of ``hub.json`` that are not checked out beside the hub."""
        ...


# Builds the sources of the hub at a registered path, with the folders of its repos.
type SourcesOf = Callable[[str, tuple[str, ...]], KnowledgeSources]
# Opens the knowledge index, or raises why it cannot (no FTS5, the database unreadable).
type IndexOpener = Callable[[], KnowledgeIndex]


class KnowledgeResult(ViewModel):
    """One search result: the document and a one-line plain-text snippet of its body."""

    path: str
    kind: Kind
    title: str
    status: str | None
    provenance: str | None
    snippet: str


class KnowledgeSyncCounts(ViewModel):
    """What the sync before the read did: files listed, read, indexed and rows dropped."""

    listed: int = Field(ge=0)
    read: int = Field(ge=0)
    indexed: int = Field(ge=0)
    dropped: int = Field(ge=0)


class KnowledgeSkip(ViewModel):
    """A listed file the index left out, and why."""

    path: str
    reason: str


class KnowledgeSearch(ViewModel):
    """A search of the project's hub: ``hub search --json``'s object, ``project`` for ``hub``,
    plus a warning per repo that is not checked out."""

    project: str
    query: str
    results: tuple[KnowledgeResult, ...]
    sync: KnowledgeSyncCounts
    skipped: tuple[KnowledgeSkip, ...]
    warnings: tuple[str, ...]


class NoteBacklink(ViewModel):
    """A document holding a link to the note: its hub-relative path, kind and title."""

    path: str
    kind: Kind
    title: str


class NoteBacklinks(ViewModel):
    """The documents linking to the note at ``path`` (under ``brain/``), by path, at most
    ``MAX_BACKLINKS``; ``total`` counts them all."""

    project: str
    path: str
    items: tuple[NoteBacklink, ...]
    total: int = Field(ge=0)


class KnowledgeReads(Protocol):
    """The knowledge routes' reads of a project's hub."""

    def search(
        self, project: str, *, query: str, kinds: tuple[Kind, ...] = (), limit: int = MAX_RESULTS
    ) -> KnowledgeSearch:
        """The hub's documents holding every word of ``query``, best first, at most ``limit``;
        ``EntityNotFoundError`` for an unknown project."""
        ...

    def backlinks(self, project: str, path: str) -> NoteBacklinks:
        """The documents linking to the note at ``path``; ``BrainPathError`` or
        ``BrainNoteNotFoundError`` for a path the note route refuses, ``EntityNotFoundError``
        for an unknown project."""
        ...


class ReadKnowledge:
    """``KnowledgeReads`` over the registered hubs, their checkouts and the knowledge index."""

    def __init__(self, hubs: HubReadModels, *, sources: SourcesOf, index: IndexOpener) -> None:
        self._hubs = hubs
        self._sources = sources
        self._index = index

    def search(
        self, project: str, *, query: str, kinds: tuple[Kind, ...] = (), limit: int = MAX_RESULTS
    ) -> KnowledgeSearch:
        """Sync the project's hub, then search it; the results cut to ``limit``."""
        name, hub_path, checkout = self._checkout(project)
        outcome = search_knowledge(
            self._index(), checkout, hub_path, words=query_words(query), kinds=kinds
        )
        return KnowledgeSearch(
            project=name,
            query=query,
            results=tuple(_result(hit) for hit in outcome.results[:limit]),
            sync=_counts(outcome.report),
            skipped=tuple(
                KnowledgeSkip(path=skipped.path, reason=skipped.reason)
                for skipped in outcome.report.skipped
            ),
            warnings=tuple(
                f"{folder}: not checked out; its docs are not searched"
                for folder in checkout.not_checked_out()
            ),
        )

    def backlinks(self, project: str, path: str) -> NoteBacklinks:
        """Sync the project's hub, then answer the documents linking to ``brain/<path>``."""
        relative = readable_note_path(path, project=project)
        name, hub_path, checkout = self._checkout(project)
        outcome = backlinks_knowledge(
            self._index(), checkout, hub_path, target=f"{BRAIN_FOLDER}/{relative}"
        )
        return NoteBacklinks(
            project=name,
            path=relative,
            items=tuple(
                NoteBacklink(path=item.path, kind=item.kind, title=item.title)
                for item in outcome.backlinks.items
            ),
            total=outcome.backlinks.total,
        )

    def _checkout(self, project: str) -> tuple[str, str, KnowledgeSources]:
        detail = self._hubs.get_project(project)
        folders = tuple(repo.dir for repo in self._hubs.project_repos(project).items)
        return detail.name, detail.hub_path, self._sources(detail.hub_path, folders)


def _result(hit: SearchHit) -> KnowledgeResult:
    return KnowledgeResult(
        path=hit.path,
        kind=hit.kind,
        title=hit.title,
        status=hit.status,
        provenance=hit.provenance,
        snippet=hit.snippet,
    )


def _counts(report: SyncReport) -> KnowledgeSyncCounts:
    return KnowledgeSyncCounts(
        listed=report.listed, read=report.read, indexed=report.indexed, dropped=report.dropped
    )
