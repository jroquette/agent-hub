"""The ``KnowledgeIndex`` contract suite: the in-memory fake and the SQLite index honour it.

An implementation's ``tests/contract/`` provides a ``knowledge_index`` fixture (an empty index)
and declares ``class Test<Implementation>(KnowledgeIndexContract)``. Checks raise
``AssertionError`` by hand: core ships this suite without depending on pytest.

Words are uninflected English, so an index that stems them (FTS5's ``porter``) and one that does
not answer alike.
"""

import hashlib
from typing import Final

from agent_hub.core.knowledge.knowledge_index import (
    INDEX_VERSION,
    Fingerprint,
    IndexChange,
    IndexedDocument,
    Kind,
    KnowledgeIndex,
    SkippedFile,
    StoredFile,
)
from agent_hub.core.knowledge.search_query import MAX_RESULTS

HUB: Final = "/hubs/demo"
OTHER_HUB: Final = "/hubs/other"
_MTIME_NS: Final = 1_760_000_000_000_000_000


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


def _document(
    path: str,
    *,
    body: str,
    title: str = "Notes",
    kind: Kind = "doc",
    status: str | None = None,
    provenance: str | None = None,
) -> IndexedDocument:
    return IndexedDocument(
        path=path,
        kind=kind,
        title=title,
        status=status,
        provenance=provenance,
        fingerprint=Fingerprint(size=len(body.encode()), mtime_ns=_MTIME_NS),
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        body=body,
    )


def _index(index: KnowledgeIndex, *documents: IndexedDocument, hub: str = HUB) -> None:
    index.apply(hub, IndexChange(version=INDEX_VERSION, documents=documents))


def _paths(
    index: KnowledgeIndex, *words: str, hub: str = HUB, kinds: tuple[Kind, ...] = ()
) -> list[str]:
    return [hit.path for hit in index.search(hub, words, kinds=kinds, limit=MAX_RESULTS)]


class KnowledgeIndexContract:
    """Search by every word, title first, kinds, limit; per-hub rows; apply as P-5 says."""

    def test_ranks_title_match_first_when_lengths_equal(
        self, knowledge_index: KnowledgeIndex
    ) -> None:
        in_body = _document(
            "brain/decisions/0001-cleanup.md",
            title="Cleanup",
            body="worktrees removed after merge",
            kind="decision",
        )
        in_title = _document(
            "brain/playbooks/worktrees.md",
            title="Worktrees",
            body="cleanup removed after merge",
            kind="playbook",
            status="accepted",
            provenance="agent",
        )
        fillers = [
            _document(f"brain/learnings/filler-{name}.md", body=f"{name} release checklist")
            for name in ("alpha", "beta", "gamma")
        ]
        _index(knowledge_index, in_body, in_title, *fillers)

        hits = knowledge_index.search(HUB, ("worktrees",), limit=MAX_RESULTS)

        paths = [hit.path for hit in hits]
        _check(paths == [in_title.path, in_body.path], f"the title match ranks first: {paths}")
        first = hits[0]
        shown = (first.kind, first.title, first.status, first.provenance)
        _check(shown == ("playbook", "Worktrees", "accepted", "agent"), f"its fields: {shown}")
        _check((hits[1].status, hits[1].provenance) == (None, None), "absent fields are None")
        _check("worktrees" in hits[1].snippet, f"the snippet holds the word: {hits[1].snippet}")
        _check("\n" not in hits[1].snippet, "the snippet is one line")

    def test_returns_only_documents_with_every_word_when_several_given(
        self, knowledge_index: KnowledgeIndex
    ) -> None:
        _index(
            knowledge_index,
            _document("brain/both.md", body="alpha and beta together"),
            _document("brain/alpha.md", body="alpha alone here"),
            _document("brain/beta.md", body="beta alone here"),
            _document("brain/title.md", title="Beta", body="alpha in the body"),
        )

        paths = _paths(knowledge_index, "alpha", "beta")

        _check(sorted(paths) == ["brain/both.md", "brain/title.md"], f"every word: {paths}")
        _check(_paths(knowledge_index, "ALPHA", "Beta") == paths, "case does not matter")
        _check(_paths(knowledge_index, "alpha", "zebra") == [], "a missing word matches nothing")

    def test_keeps_listed_kinds_when_kind_filter_given(
        self, knowledge_index: KnowledgeIndex
    ) -> None:
        kinds: tuple[Kind, ...] = ("feature", "adr", "decision", "doc")
        _index(
            knowledge_index,
            *(_document(f"brain/{kind}.md", body="marker text", kind=kind) for kind in kinds),
        )

        paths = _paths(knowledge_index, "marker", kinds=("feature", "adr"))

        _check(sorted(paths) == ["brain/adr.md", "brain/feature.md"], f"listed kinds: {paths}")
        _check(len(_paths(knowledge_index, "marker")) == 4, "no filter: every kind")

    def test_returns_at_most_limit_when_more_match(self, knowledge_index: KnowledgeIndex) -> None:
        _index(
            knowledge_index,
            *(_document(f"brain/features/f{n:02}.md", body="marker text") for n in range(60)),
        )

        paths = _paths(knowledge_index, "marker")

        _check(len(paths) == MAX_RESULTS, f"at most the limit: {len(paths)}")
        _check(len(set(paths)) == MAX_RESULTS, "each document once")

    def test_never_returns_other_hub_when_words_match_both(
        self, knowledge_index: KnowledgeIndex
    ) -> None:
        path = "brain/now.md"
        _index(knowledge_index, _document(path, title="Ours", body="marker text"))
        _index(knowledge_index, _document(path, title="Theirs", body="marker text"), hub=OTHER_HUB)

        hits = knowledge_index.search(HUB, ("marker",), limit=MAX_RESULTS)

        _check([hit.title for hit in hits] == ["Ours"], f"only the hub's own row: {hits}")
        _check(knowledge_index.search("/hubs/none", ("marker",), limit=MAX_RESULTS) == (), "none")

    def test_leaves_other_hub_when_hub_rebuilt(self, knowledge_index: KnowledgeIndex) -> None:
        old = (
            _document("brain/a.md", body="alpha text"),
            _document("brain/b.md", body="beta text"),
        )
        _index(knowledge_index, *old)
        _index(knowledge_index, *old, hub=OTHER_HUB)
        rebuilt = _document("brain/c.md", body="gamma text")

        knowledge_index.apply(
            HUB, IndexChange(version=INDEX_VERSION, rebuild=True, documents=(rebuilt,))
        )

        ours = set(knowledge_index.stored(HUB).files)
        theirs = set(knowledge_index.stored(OTHER_HUB).files)
        _check(ours == {"brain/c.md"}, f"the hub holds only the rebuilt rows: {ours}")
        _check(theirs == {"brain/a.md", "brain/b.md"}, f"the other hub is untouched: {theirs}")
        _check(_paths(knowledge_index, "alpha") == [], "the dropped text is not found")
        _check(_paths(knowledge_index, "alpha", hub=OTHER_HUB) == ["brain/a.md"], "theirs is")

    def test_replaces_document_when_applied_twice(self, knowledge_index: KnowledgeIndex) -> None:
        first = _document("brain/now.md", body="alpha text")
        second = _document("brain/now.md", title="Now", body="beta words longer")
        _index(knowledge_index, first)

        _index(knowledge_index, second)

        files = knowledge_index.stored(HUB).files
        expected = StoredFile(
            path=second.path, fingerprint=second.fingerprint, sha256=second.sha256
        )
        _check(dict(files) == {second.path: expected}, f"one row, the second: {files}")
        _check(_paths(knowledge_index, "beta") == ["brain/now.md"], "the new text is found")
        _check(_paths(knowledge_index, "alpha") == [], "the old text is not")

    def test_drops_document_when_change_drops_path(self, knowledge_index: KnowledgeIndex) -> None:
        _index(
            knowledge_index,
            _document("brain/a.md", body="marker alpha"),
            _document("brain/b.md", body="marker beta"),
        )

        knowledge_index.apply(
            HUB, IndexChange(version=INDEX_VERSION, dropped=("brain/a.md", "brain/never.md"))
        )

        _check(set(knowledge_index.stored(HUB).files) == {"brain/b.md"}, "the row is dropped")
        _check(_paths(knowledge_index, "marker") == ["brain/b.md"], "its text is not found")

    def test_updates_fingerprint_when_touched(self, knowledge_index: KnowledgeIndex) -> None:
        document = _document("brain/now.md", body="marker text")
        _index(knowledge_index, document)
        touched = Fingerprint(size=document.fingerprint.size, mtime_ns=_MTIME_NS + 1)

        knowledge_index.apply(
            HUB, IndexChange(version=INDEX_VERSION, touched={document.path: touched})
        )

        stored = knowledge_index.stored(HUB).files[document.path]
        expected = StoredFile(path=document.path, fingerprint=touched, sha256=document.sha256)
        _check(stored == expected, f"the new fingerprint, the same hash: {stored}")
        _check(_paths(knowledge_index, "marker") == [document.path], "the text is kept")

    def test_stores_skipped_file_without_text_when_skip_applied(
        self, knowledge_index: KnowledgeIndex
    ) -> None:
        leak = _document("brain/_inbox/leak.md", body="marker text")
        gone = _document("brain/gone.md", body="marker text")
        _index(knowledge_index, leak, gone)
        big = Fingerprint(size=262_145, mtime_ns=_MTIME_NS)
        skipped = (
            SkippedFile(
                path=leak.path, fingerprint=leak.fingerprint, reason="matches a secret rule"
            ),
            SkippedFile(path="brain/big.md", fingerprint=big, reason="larger than 256 KiB"),
            SkippedFile(path=gone.path, fingerprint=None, reason="cannot be read"),
        )

        knowledge_index.apply(HUB, IndexChange(version=INDEX_VERSION, skipped=skipped))

        files = knowledge_index.stored(HUB).files
        expected = {
            leak.path: StoredFile(
                path=leak.path, fingerprint=leak.fingerprint, skip_reason="matches a secret rule"
            ),
            "brain/big.md": StoredFile(
                path="brain/big.md", fingerprint=big, skip_reason="larger than 256 KiB"
            ),
        }
        _check(dict(files) == expected, f"fingerprint and reason, no hash, no row without: {files}")
        _check(_paths(knowledge_index, "marker") == [], "a skipped file is never found")

    def test_keeps_version_when_change_applied(self, knowledge_index: KnowledgeIndex) -> None:
        empty = knowledge_index.stored(HUB)
        _check((empty.version, dict(empty.files)) == (None, {}), f"no row: {empty}")
        first = _document("brain/a.md", body="alpha text")
        _index(knowledge_index, first, _document("brain/b.md", body="beta text"))
        _check(knowledge_index.stored(HUB).version == INDEX_VERSION, "the change's version")

        newer = INDEX_VERSION + 1
        knowledge_index.apply(
            HUB, IndexChange(version=newer, touched={first.path: first.fingerprint})
        )
        _check(knowledge_index.stored(HUB).version is None, "rows that disagree have none")

        knowledge_index.apply(HUB, IndexChange(version=newer, rebuild=True, documents=(first,)))
        _check(knowledge_index.stored(HUB).version == newer, "a rebuild sets every row's")
        _check(knowledge_index.stored(OTHER_HUB).version is None, "another hub has none")
