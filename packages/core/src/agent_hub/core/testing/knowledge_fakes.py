"""``InMemoryKnowledgeIndex``: the ``KnowledgeIndex`` port over dictionaries, one per hub."""

import threading
from collections import Counter
from dataclasses import dataclass
from typing import Final

from agent_hub.core.knowledge.knowledge_index import (
    IndexChange,
    IndexedDocument,
    Kind,
    SearchHit,
    StoredFile,
    StoredIndex,
)
from agent_hub.core.knowledge.search_query import query_words, snippet_line

# A word in the title counts this many times a word in the body (D-query's weights 10 and 1).
_TITLE_WEIGHT: Final = 10


@dataclass(frozen=True)
class _Row:
    """What a row holds: the file as a sync sees it, the version that wrote it, and the indexed
    text (None for a skipped file)."""

    file: StoredFile
    version: int
    document: IndexedDocument | None = None


class InMemoryKnowledgeIndex:
    """Each hub's rows by path, behind one lock; behaves as ``KnowledgeIndexContract`` says.

    A document scores ``10 × title hits + body hits`` over the casefolded words of each text, with
    no stemming (the contract's words are uninflected)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, _Row]] = {}

    def stored(self, hub: str) -> StoredIndex:
        """What the hub's rows remember, by path."""
        with self._lock:
            rows = dict(self._rows.get(hub, {}))
        versions = {row.version for row in rows.values()}
        return StoredIndex(
            version=versions.pop() if len(versions) == 1 else None,
            files={path: row.file for path, row in rows.items()},
        )

    def apply(self, hub: str, change: IndexChange) -> None:
        """Write ``change`` to the hub's rows: rebuild, documents, skipped, touched, dropped."""
        version = change.version
        with self._lock:
            rows = {} if change.rebuild else dict(self._rows.get(hub, {}))
            for document in change.documents:
                file = StoredFile(
                    path=document.path, fingerprint=document.fingerprint, sha256=document.sha256
                )
                rows[document.path] = _Row(file, version, document)
            for skipped in change.skipped:
                rows.pop(skipped.path, None)
                if skipped.fingerprint is not None:
                    file = StoredFile(
                        path=skipped.path,
                        fingerprint=skipped.fingerprint,
                        skip_reason=skipped.reason,
                    )
                    rows[skipped.path] = _Row(file, version)
            for path, fingerprint in change.touched.items():
                if (row := rows.get(path)) is not None:
                    file = row.file.model_copy(update={"fingerprint": fingerprint})
                    rows[path] = _Row(file, version, row.document)
            for path in change.dropped:
                rows.pop(path, None)
            self._rows[hub] = rows

    def search(
        self, hub: str, words: tuple[str, ...], *, kinds: tuple[Kind, ...] = (), limit: int
    ) -> tuple[SearchHit, ...]:
        """The hub's documents holding every word, best first, then by path."""
        with self._lock:
            rows = list(self._rows.get(hub, {}).values())
        documents = [row.document for row in rows if row.document is not None]
        wanted = [word.casefold() for word in words]
        scored = [
            (score, document)
            for document in documents
            if not kinds or document.kind in kinds
            if (score := _score(document, wanted)) is not None
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].path))
        return tuple(_hit(document) for _, document in scored[:limit])


def _score(document: IndexedDocument, words: list[str]) -> int | None:
    """The document's score, or None when a word is in neither its title nor its body."""
    title = Counter(word.casefold() for word in query_words(document.title))
    body = Counter(word.casefold() for word in query_words(document.body))
    if not words or any(title[word] + body[word] == 0 for word in words):
        return None
    return sum(_TITLE_WEIGHT * title[word] + body[word] for word in words)


def _hit(document: IndexedDocument) -> SearchHit:
    return SearchHit(
        path=document.path,
        kind=document.kind,
        title=document.title,
        status=document.status,
        provenance=document.provenance,
        snippet=snippet_line(document.body),
    )
