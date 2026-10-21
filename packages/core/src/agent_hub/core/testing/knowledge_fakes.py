"""``InMemoryKnowledgeIndex``: the ``KnowledgeIndex`` port over dictionaries, one per hub."""

import threading
from collections import Counter
from typing import Final

from agent_hub.core.knowledge.knowledge_index import (
    IndexChange,
    IndexedDocument,
    Kind,
    SearchHit,
    StoredIndex,
)
from agent_hub.core.knowledge.search_query import query_words, snippet_line

# A word in the title counts this many times a word in the body (D-query's weights 10 and 1).
_TITLE_WEIGHT: Final = 10


class InMemoryKnowledgeIndex:
    """Each hub's rows by path, behind one lock; behaves as ``KnowledgeIndexContract`` says.

    A document scores ``10 × title hits + body hits`` over the casefolded words of each text, with
    no stemming (the contract's words are uninflected)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._documents: dict[str, dict[str, IndexedDocument]] = {}

    def stored(self, hub: str) -> StoredIndex:
        """What the hub's rows remember, by path."""
        raise NotImplementedError

    def apply(self, hub: str, change: IndexChange) -> None:
        """Write ``change`` to the hub's rows."""
        with self._lock:
            documents = self._documents.setdefault(hub, {})
            for document in change.documents:
                documents[document.path] = document

    def search(
        self, hub: str, words: tuple[str, ...], *, kinds: tuple[Kind, ...] = (), limit: int
    ) -> tuple[SearchHit, ...]:
        """The hub's documents holding every word, best first, then by path."""
        with self._lock:
            documents = list(self._documents.get(hub, {}).values())
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
