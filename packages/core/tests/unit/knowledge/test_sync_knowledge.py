"""Syncing a hub's knowledge rows with its checkout, then searching them (AGH-391, D-sync,
D-reindex, D-version, D-skipreport, AM-1): over the in-memory index and checkout."""

import pytest

from agent_hub.core.knowledge import document_rules
from agent_hub.core.knowledge.document_rules import RULE_MATCH, THROUGH_LINK, UNREADABLE
from agent_hub.core.knowledge.knowledge_index import (
    INDEX_VERSION,
    MAX_BACKLINKS,
    Backlink,
    IndexChange,
    SkippedFile,
)
from agent_hub.core.knowledge.search_query import MAX_RESULTS
from agent_hub.core.knowledge.sync_knowledge import (
    KnowledgeCheckoutError,
    SyncReport,
    backlinks_knowledge,
    search_knowledge,
    sync_knowledge,
)
from agent_hub.core.testing.knowledge_fakes import FakeKnowledgeCheckout, InMemoryKnowledgeIndex

HUB = "/hubs/demo"
OTHER = "/hubs/other"


class _CountingIndex(InMemoryKnowledgeIndex):
    """The in-memory index, counting the changes applied."""

    def __init__(self) -> None:
        super().__init__()
        self.applied: list[IndexChange] = []

    def apply(self, hub: str, change: IndexChange) -> None:
        self.applied.append(change)
        super().apply(hub, change)


def _token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def _checkout(**files: str) -> FakeKnowledgeCheckout:
    checkout = FakeKnowledgeCheckout()
    for name, text in files.items():
        checkout.write(f"brain/playbooks/{name}.md", text.encode())
    return checkout


def _paths(index: InMemoryKnowledgeIndex, *words: str) -> list[str]:
    return [hit.path for hit in index.search(HUB, words, limit=MAX_RESULTS)]


def test_writes_nothing_when_hub_unchanged() -> None:
    index = _CountingIndex()
    checkout = _checkout(a="alpha", b="beta")
    sync_knowledge(index, checkout, HUB)
    checkout.reads.clear()

    report = sync_knowledge(index, checkout, HUB)

    assert report == SyncReport(listed=2, read=0, indexed=0, dropped=0, skipped=())
    assert checkout.reads == []
    assert len(index.applied) == 1


def test_counts_reads_when_one_file_changed() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="alpha", b="beta", c="gamma")
    first = sync_knowledge(index, checkout, HUB)
    checkout.write("brain/playbooks/b.md", b"delta")

    report = sync_knowledge(index, checkout, HUB)

    assert first == SyncReport(listed=3, read=3, indexed=3, dropped=0, skipped=())
    assert report == SyncReport(listed=3, read=1, indexed=1, dropped=0, skipped=())
    assert _paths(index, "delta") == ["brain/playbooks/b.md"]
    assert _paths(index, "beta") == []


def test_updates_fingerprint_only_when_hash_unchanged() -> None:
    index = _CountingIndex()
    checkout = _checkout(a="alpha")
    sync_knowledge(index, checkout, HUB)
    checkout.touch("brain/playbooks/a.md")

    touched = sync_knowledge(index, checkout, HUB)
    after = sync_knowledge(index, checkout, HUB)

    assert touched == SyncReport(listed=1, read=1, indexed=0, dropped=0, skipped=())
    assert index.applied[-1].touched == {
        "brain/playbooks/a.md": checkout.fingerprint("brain/playbooks/a.md")
    }
    assert after.read == 0
    assert _paths(index, "alpha") == ["brain/playbooks/a.md"]


def test_reports_skipped_file_once_when_unchanged() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(leak=f"marker {_token()}")
    checkout.skip_when_listed(
        "brain/link.md", THROUGH_LINK, fingerprint=checkout.fingerprint("brain/playbooks/leak.md")
    )

    first = sync_knowledge(index, checkout, HUB)
    second = sync_knowledge(index, checkout, HUB)

    assert [(skip.path, skip.reason) for skip in first.skipped] == [
        ("brain/link.md", THROUGH_LINK),
        ("brain/playbooks/leak.md", RULE_MATCH),
    ]
    assert second.skipped == ()
    assert second.read == 0
    assert _paths(index, "marker") == []


def test_reports_unreadable_file_again_when_unchanged() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(locked="marker")
    checkout.answer_read("brain/playbooks/locked.md", UNREADABLE)

    first = sync_knowledge(index, checkout, HUB)
    second = sync_knowledge(index, checkout, HUB)

    expected = (SkippedFile(path="brain/playbooks/locked.md", fingerprint=None, reason=UNREADABLE),)
    assert first.skipped == expected
    assert second.skipped == expected
    assert index.stored(HUB).files == {}


def test_keeps_listed_fingerprint_when_read_gives_other_reason() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(swapped="marker")
    checkout.answer_read("brain/playbooks/swapped.md", THROUGH_LINK)

    report = sync_knowledge(index, checkout, HUB)

    fingerprint = checkout.fingerprint("brain/playbooks/swapped.md")
    assert report.skipped == (
        SkippedFile(
            path="brain/playbooks/swapped.md", fingerprint=fingerprint, reason=THROUGH_LINK
        ),
    )


def test_drops_row_when_file_vanishes_before_read() -> None:
    index = _CountingIndex()
    checkout = _checkout(a="alpha")
    sync_knowledge(index, checkout, HUB)
    checkout.write("brain/playbooks/a.md", b"alpha two")
    checkout.write("brain/playbooks/new.md", b"fresh")
    checkout.answer_read("brain/playbooks/a.md", None)
    checkout.answer_read("brain/playbooks/new.md", None)

    report = sync_knowledge(index, checkout, HUB)

    assert report == SyncReport(listed=2, read=2, indexed=0, dropped=1, skipped=())
    assert index.applied[-1].dropped == ("brain/playbooks/a.md",)
    assert index.stored(HUB).files == {}


def test_drops_row_when_file_no_longer_listed() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="alpha", b="beta")
    sync_knowledge(index, checkout, HUB)
    checkout.remove("brain/playbooks/a.md")

    report = sync_knowledge(index, checkout, HUB)

    assert report == SyncReport(listed=1, read=0, indexed=0, dropped=1, skipped=())
    assert _paths(index, "alpha") == []


def test_rebuilds_hub_when_reindex_requested() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="alpha", leak=f"marker {_token()}")
    other = _checkout(z="alpha")
    sync_knowledge(index, other, OTHER)
    sync_knowledge(index, checkout, HUB)
    # Same size, same mtime: only a rebuild sees the new text.
    mtime_ns = checkout.fingerprint("brain/playbooks/a.md").mtime_ns
    checkout.write("brain/playbooks/a.md", b"omega", mtime_ns=mtime_ns)

    report = sync_knowledge(index, checkout, HUB, rebuild=True)

    assert (report.listed, report.read, report.indexed) == (2, 2, 1)
    assert [skip.path for skip in report.skipped] == ["brain/playbooks/leak.md"]
    assert _paths(index, "omega") == ["brain/playbooks/a.md"]
    assert _paths(index, "alpha") == []
    other_hits = index.search(OTHER, ("alpha",), limit=MAX_RESULTS)
    assert [hit.path for hit in other_hits] == ["brain/playbooks/z.md"]


def test_rebuilds_hub_when_stored_version_differs() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="alpha", b="beta")
    sync_knowledge(index, checkout, HUB)
    older = {path: file.fingerprint for path, file in index.stored(HUB).files.items()}
    index.apply(HUB, IndexChange(version=INDEX_VERSION - 1, touched=older))

    report = sync_knowledge(index, checkout, HUB)

    assert report.read == report.listed == 2
    assert index.stored(HUB).version == INDEX_VERSION


def test_counts_unlisted_rows_as_dropped_when_stored_version_differs() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="alpha", b="beta", c="gamma")
    sync_knowledge(index, checkout, HUB)
    older = {path: file.fingerprint for path, file in index.stored(HUB).files.items()}
    index.apply(HUB, IndexChange(version=INDEX_VERSION - 1, touched=older))
    checkout.remove("brain/playbooks/a.md")
    checkout.remove("brain/playbooks/b.md")

    report = sync_knowledge(index, checkout, HUB)

    assert report == SyncReport(listed=1, read=1, indexed=1, dropped=2, skipped=())
    assert list(index.stored(HUB).files) == ["brain/playbooks/c.md"]


def test_counts_dropped_rows_when_reindex_requested() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="alpha", b="beta", c="gamma")
    sync_knowledge(index, checkout, HUB)
    checkout.remove("brain/playbooks/a.md")
    checkout.answer_read("brain/playbooks/c.md", None)

    report = sync_knowledge(index, checkout, HUB, rebuild=True)

    # a is no longer listed, c vanished before its read: both rows are gone.
    assert report == SyncReport(listed=2, read=2, indexed=1, dropped=2, skipped=())
    assert list(index.stored(HUB).files) == ["brain/playbooks/b.md"]


def test_counts_nothing_dropped_when_reindex_finds_same_files() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="alpha", b="beta")
    sync_knowledge(index, checkout, HUB)

    report = sync_knowledge(index, checkout, HUB, rebuild=True)

    assert report == SyncReport(listed=2, read=2, indexed=2, dropped=0, skipped=())


def test_stops_before_any_read_when_listing_over_file_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(document_rules, "MAX_LISTED_FILES", 3)
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="a", b="b", c="c", d="d")

    with pytest.raises(KnowledgeCheckoutError) as raised:
        sync_knowledge(index, checkout, HUB)

    assert str(raised.value) == (
        "4 Markdown files under the hub's sources, more than 3; nothing was indexed"
    )
    assert checkout.reads == []
    assert index.stored(HUB).files == {}


def test_searches_after_sync_when_query_given() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(a="marker alpha")
    checkout.write("brain/decisions/0001-x.md", b"# Marker\n\nalpha")

    outcome = search_knowledge(index, checkout, HUB, words=("marker",))
    decisions = search_knowledge(index, checkout, HUB, words=("marker",), kinds=("decision",))

    assert [hit.path for hit in outcome.results] == [
        "brain/decisions/0001-x.md",
        "brain/playbooks/a.md",
    ]
    assert outcome.report.indexed == 2
    assert [hit.path for hit in decisions.results] == ["brain/decisions/0001-x.md"]
    assert decisions.report.read == 0


def test_indexes_links_when_note_links_brain() -> None:
    index = _CountingIndex()
    checkout = _checkout(cleanup="# Cleanup\n\nSee [now](../now.md).\n")
    checkout.write("demo-api/docs/guide.md", b"[now](../../demo-hub/brain/now.md)\n")

    sync_knowledge(index, checkout, "/w/demo-hub")

    links = {document.path: document.links for document in index.applied[0].documents}
    assert links == {
        "brain/playbooks/cleanup.md": ("brain/now.md",),
        "demo-api/docs/guide.md": ("brain/now.md",),
    }


def test_syncs_before_backlinks_when_note_edited() -> None:
    index = InMemoryKnowledgeIndex()
    checkout = _checkout(cleanup="# Cleanup\n\nSee [now](../now.md).\n", other="# Other\n")
    first = backlinks_knowledge(index, checkout, HUB, target="brain/now.md")
    checkout.write("brain/playbooks/cleanup.md", b"# Cleanup\n\nNo link left.\n")

    after = backlinks_knowledge(index, checkout, HUB, target="brain/now.md")

    assert first.backlinks.items == (
        Backlink(path="brain/playbooks/cleanup.md", kind="playbook", title="Cleanup"),
    )
    assert first.report.indexed == 2
    assert (after.backlinks.items, after.backlinks.total) == ((), 0)
    assert after.report == SyncReport(listed=2, read=1, indexed=1, dropped=0, skipped=())


def test_answers_sources_when_target_missing() -> None:
    index = InMemoryKnowledgeIndex()
    links = "[g](../gone.md) " * 3
    checkout = _checkout(
        **{f"n{number:03d}": f"# N{number}\n\n{links}\n" for number in range(MAX_BACKLINKS + 5)}
    )

    outcome = backlinks_knowledge(index, checkout, HUB, target="brain/gone.md")

    assert outcome.backlinks.total == MAX_BACKLINKS + 5
    assert len(outcome.backlinks.items) == MAX_BACKLINKS
    assert outcome.backlinks.items[0].path == "brain/playbooks/n000.md"
    assert index.stored(HUB).files.keys() >= {"brain/playbooks/n000.md"}
    assert "brain/gone.md" not in index.stored(HUB).files
