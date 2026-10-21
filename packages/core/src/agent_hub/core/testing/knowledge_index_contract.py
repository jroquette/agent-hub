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
    """Search by every word, title first, kinds, limit; per-hub rows; apply as one change."""

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
