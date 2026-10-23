"""``InMemoryKnowledgeIndex``: the ``KnowledgeIndex`` port over dictionaries, one per hub; and
``FakeKnowledgeCheckout``: a hub checkout held in memory."""

import re
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from agent_hub.core.knowledge.knowledge_index import (
    Backlink,
    Backlinks,
    Fingerprint,
    IndexChange,
    IndexedDocument,
    Kind,
    SearchHit,
    StoredFile,
    StoredIndex,
)
from agent_hub.core.knowledge.search_query import MAX_SNIPPET_CHARS, query_words, snippet_line
from agent_hub.core.knowledge.sync_plan import ListedFile

# A word in the title counts this many times a word in the body (D-query's weights 10 and 1).
_TITLE_WEIGHT: Final = 10
# A word as ``query_words`` splits it, to find where the first match sits in a body.
_WORD: Final = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class _Row:
    """What a row holds: the file as a sync sees it, the version that wrote it, and the indexed
    text and links (None for a skipped file). A row's links live and die with its document, so
    a re-indexed document replaces them, a touched one keeps them, and a skipped, dropped or
    rebuilt path loses them."""

    file: StoredFile
    version: int
    document: IndexedDocument | None = None


class InMemoryKnowledgeIndex:
    """Each hub's rows by path, behind one lock; behaves as ``KnowledgeIndexContract`` says.

    A document scores ``10 × title hits + body hits`` over the casefolded words of each text, with
    no stemming (each of the contract's query words appears in the documents in the same form, so
    stemming does not change the answer)."""

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
        return tuple(_hit(document, wanted) for _, document in scored[:limit])

    def backlinks(self, hub: str, target: str, *, limit: int) -> Backlinks:
        """The hub's documents linking to ``target``, by path, at most ``limit``, all counted."""
        with self._lock:
            rows = list(self._rows.get(hub, {}).values())
        sources = sorted(
            (row.document for row in rows if row.document and target in row.document.links),
            key=lambda document: document.path,
        )
        items = tuple(
            Backlink(path=source.path, kind=source.kind, title=source.title)
            for source in sources[:limit]
        )
        return Backlinks(items=items, total=len(sources))


def _score(document: IndexedDocument, words: list[str]) -> int | None:
    """The document's score, or None when a word is in neither its title nor its body."""
    title = Counter(word.casefold() for word in query_words(document.title))
    body = Counter(word.casefold() for word in query_words(document.body))
    if not words or any(title[word] + body[word] == 0 for word in words):
        return None
    return sum(_TITLE_WEIGHT * title[word] + body[word] for word in words)


def _hit(document: IndexedDocument, words: list[str]) -> SearchHit:
    return SearchHit(
        path=document.path,
        kind=document.kind,
        title=document.title,
        status=document.status,
        provenance=document.provenance,
        snippet=_snippet(document.body, words),
    )


def _snippet(body: str, words: list[str]) -> str:
    """One line of the body around its first matching word, ``…`` where cut (as FTS5's
    ``snippet()`` then ``snippet_line``); the body's start when only the title matches."""
    line = " ".join(body.split())
    first = next(
        (match.start() for match in _WORD.finditer(line) if match.group().casefold() in words), 0
    )
    start = max(0, first - MAX_SNIPPET_CHARS // 2)
    return snippet_line(("…" if start else "") + line[start:])


class FakeKnowledgeCheckout:
    """A ``KnowledgeCheckout`` over files held in memory, by hub-relative path.

    ``write`` sets a file's bytes and moves its mtime on (or sets ``mtime_ns``), ``touch`` moves
    only the mtime, ``remove`` deletes it. ``skip_when_listed`` lists a path with a skip reason,
    ``answer_read`` makes its read return a reason (a ``str``) or None (gone since the listing).
    ``reads`` holds the paths read, in order; ``before_read`` runs before each read (a test's
    barrier). ``missing`` names the repo folders ``not_checked_out`` reports.
    """

    def __init__(self, *, before_read: Callable[[str], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, tuple[bytes, int]] = {}
        self._clock = 0
        self._listing_skips: dict[str, ListedFile] = {}
        self._read_answers: dict[str, str | None] = {}
        self._before_read = before_read
        self.reads: list[str] = []
        self.missing: tuple[str, ...] = ()

    def write(self, path: str, data: bytes, *, mtime_ns: int | None = None) -> None:
        """Set the file's bytes; its mtime moves on unless ``mtime_ns`` is given."""
        self._files[path] = (data, self._next_mtime() if mtime_ns is None else mtime_ns)

    def touch(self, path: str) -> None:
        """Move the file's mtime on, its bytes unchanged."""
        data, _ = self._files[path]
        self._files[path] = (data, self._next_mtime())

    def remove(self, path: str) -> None:
        """Delete the file."""
        del self._files[path]

    def fingerprint(self, path: str) -> Fingerprint:
        """The fingerprint the listing gives the file."""
        data, mtime_ns = self._files[path]
        return Fingerprint(size=len(data), mtime_ns=mtime_ns)

    def skip_when_listed(
        self, path: str, reason: str, *, fingerprint: Fingerprint | None = None
    ) -> None:
        """List ``path`` as ruled out by the listing (a link, a FIFO, a name not UTF-8)."""
        self._listing_skips[path] = ListedFile(
            path=path, fingerprint=fingerprint, skip_reason=reason
        )

    def answer_read(self, path: str, answer: str | None) -> None:
        """Make the read of ``path`` return ``answer`` instead of its bytes."""
        self._read_answers[path] = answer

    def not_checked_out(self) -> tuple[str, ...]:
        """The repo folders set in ``missing``, as a checkout that cannot find them names them."""
        return self.missing

    def listed(self) -> tuple[ListedFile, ...]:
        """Every file and listed skip, sorted by path."""
        files = {
            path: ListedFile(path=path, fingerprint=self.fingerprint(path)) for path in self._files
        }
        files.update(self._listing_skips)
        return tuple(files[path] for path in sorted(files))

    def read(self, path: str) -> bytes | str | None:
        """The file's bytes, the answer set for it, or None when it is gone."""
        if self._before_read is not None:
            self._before_read(path)
        with self._lock:
            self.reads.append(path)
        if path in self._read_answers:
            return self._read_answers[path]
        found = self._files.get(path)
        return None if found is None else found[0]

    def _next_mtime(self) -> int:
        self._clock += 1
        return 1_700_000_000_000_000_000 + self._clock
