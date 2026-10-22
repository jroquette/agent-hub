"""The ``KnowledgeIndex`` port: a hub's searchable documents, derived from its checkout (AGH-391,
ADR 0044).

Synchronous (SQLite FTS5 in production). ``KnowledgeIndexContract`` checks every implementation:

- Rows are keyed by ``(hub, path)``; a hub's rows are never read, returned or dropped through
  another hub.
- ``stored`` answers what a hub's rows remember: each file's fingerprint, the hash of an indexed
  file's text, the reason a skipped file was left out, and the index version of the rows.
- ``apply`` writes one ``IndexChange`` in one transaction: with ``rebuild`` the hub's rows are
  dropped first; a document or a skipped file replaces the row of its path; a touched path keeps
  its text and gets the new fingerprint; a dropped path loses its row. Every row the change writes
  gets the change's ``version``. A skipped file keeps no text, so a search never returns it.
- ``search`` answers the hub's documents holding every word, a title match weighted above a body
  match, best first and then by path, at most ``limit``, of the listed kinds only when given;
  none when no word is given. A hit's snippet is one line around the first match in the body.

``KnowledgeLinksContract`` checks each document's links (AGH-393):

- A document's links are written with it and replaced when it is indexed again; a touched path
  keeps them; a skipped or dropped path loses them, and a rebuild drops the hub's.
- ``backlinks`` answers the hub's documents linking to a note, sorted by path, at most ``limit``,
  with the full count; a note that is not indexed (a dead link) still has its sources.
"""

from collections.abc import Mapping
from typing import Annotated, Final, Literal, Protocol, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

# What a document is, from its folder (D-kind).
type Kind = Literal[
    "adr",
    "decision",
    "doc",
    "domain",
    "feature",
    "inbox",
    "journal",
    "learning",
    "playbook",
    "system",
]

KINDS: Final[tuple[Kind, ...]] = get_args(Kind.__value__)

# Bumped by any change to what is indexed or how (D-version): a hub whose rows hold another
# version is rebuilt by the next search. 2: each document's links to brain notes are stored.
INDEX_VERSION: Final = 2

# At most this many backlinks are answered for one note (D-backlinks-route), with the full count.
MAX_BACKLINKS: Final = 100

# A file's text hash: 64 lowercase hex digits of its sha256.
type TextHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Fingerprint(_Frozen):
    """What a sync compares to notice a change without reading the file: its size and mtime."""

    size: int = Field(ge=0)
    mtime_ns: int


class StoredFile(_Frozen):
    """A hub row as a sync sees it: an indexed file has a hash, a skipped one a reason."""

    path: str = Field(min_length=1)
    fingerprint: Fingerprint
    sha256: TextHash | None = None
    skip_reason: str | None = None

    @model_validator(mode="after")
    def _indexed_or_skipped(self) -> Self:
        if (self.sha256 is None) == (self.skip_reason is None):
            msg = "a stored file has exactly one of sha256 and skip_reason"
            raise ValueError(msg)
        return self


class StoredIndex(_Frozen):
    """A hub's rows by path. ``version`` is the index version every row shares; None when the
    hub has no row or its rows disagree."""

    version: int | None
    files: Mapping[str, StoredFile]


class IndexedDocument(_Frozen):
    """A file to index: its searchable title and body, what a result shows, and the brain notes
    it links to (``brain/<rest>``, D-links)."""

    path: str = Field(min_length=1)
    kind: Kind
    title: str
    status: str | None = None
    provenance: str | None = None
    fingerprint: Fingerprint
    sha256: TextHash
    body: str
    links: tuple[str, ...] = ()


class SkippedFile(_Frozen):
    """A listed file left out of the index, and why. Without a fingerprint nothing of it can be
    remembered, so its row (if any) is dropped."""

    path: str = Field(min_length=1)
    fingerprint: Fingerprint | None
    reason: str = Field(min_length=1)


class IndexChange(_Frozen):
    """What one sync writes to a hub's rows, in one transaction."""

    version: int
    rebuild: bool = False
    documents: tuple[IndexedDocument, ...] = ()
    skipped: tuple[SkippedFile, ...] = ()
    touched: Mapping[str, Fingerprint] = Field(default_factory=dict)
    dropped: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when applying the change would write nothing."""
        return not (self.rebuild or self.documents or self.skipped or self.touched or self.dropped)


class SearchHit(_Frozen):
    """One search result: the document and a one-line snippet of its body."""

    path: str
    kind: Kind
    title: str
    status: str | None
    provenance: str | None
    snippet: str


class Backlink(_Frozen):
    """A document holding a link to a note: its path, kind and title."""

    path: str
    kind: Kind
    title: str


class Backlinks(_Frozen):
    """The documents linking to a note, by path, at most the limit asked; ``total`` counts all."""

    items: tuple[Backlink, ...]
    total: int = Field(ge=0)


class KnowledgeIndex(Protocol):
    """Where the documents of each hub are indexed for search."""

    def stored(self, hub: str) -> StoredIndex:
        """What the hub's rows remember, by path."""
        ...

    def apply(self, hub: str, change: IndexChange) -> None:
        """Write ``change`` to the hub's rows, in one transaction."""
        ...

    def search(
        self, hub: str, words: tuple[str, ...], *, kinds: tuple[Kind, ...] = (), limit: int
    ) -> tuple[SearchHit, ...]:
        """The hub's documents holding every word, best first, of ``kinds`` when not empty.

        ``words`` are the non-empty output of ``query_words``; with no word the answer is ``()``."""
        ...

    def backlinks(self, hub: str, target: str, *, limit: int) -> Backlinks:
        """The hub's documents linking to ``target`` (``brain/<rest>``), by path, at most
        ``limit``, with the full count."""
        ...
