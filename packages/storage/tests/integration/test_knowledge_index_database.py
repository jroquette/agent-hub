"""The SQLite knowledge index on a real file: the FTS5 probe, an unusable path, porter stemming,
the snippet FTS5 cuts, drops past SQLite's variable limit, an apply that fails partway, and syncs
through it (a version rebuild, two syncs at once), with each document's links."""

import hashlib
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from agent_hub.core.knowledge.knowledge_index import (
    INDEX_VERSION,
    MAX_BACKLINKS,
    Fingerprint,
    IndexChange,
    IndexedDocument,
    SkippedFile,
)
from agent_hub.core.knowledge.search_query import MAX_RESULTS, MAX_SNIPPET_CHARS
from agent_hub.core.knowledge.sync_knowledge import sync_knowledge
from agent_hub.core.testing.knowledge_fakes import FakeKnowledgeCheckout
from agent_hub.storage.errors import DatabaseAccessError, Fts5UnavailableError, StorageError
from agent_hub.storage.knowledge_index import (
    SqliteKnowledgeIndex,
    fts5_available,
    open_knowledge_index,
)

NO_FTS5: Final = "no such module: fts5"
HUB: Final = "/hubs/demo"
# More paths than SQLite binds in one statement (SQLITE_MAX_VARIABLE_NUMBER, 32766).
_OVER_VARIABLE_LIMIT: Final = 33_000


class _NoFts5Connection:
    """A ``sqlite3`` connection of an interpreter built without the FTS5 module."""

    def execute(self, sql: str, /) -> object:
        raise sqlite3.OperationalError(NO_FTS5)

    def close(self) -> None:
        pass


def _connect_without_fts5(database: str) -> _NoFts5Connection:
    return _NoFts5Connection()


def _document(path: str, body: str) -> IndexedDocument:
    return IndexedDocument(
        path=path,
        kind="playbook",
        title="Notes",
        fingerprint=Fingerprint(size=len(body.encode()), mtime_ns=1),
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        body=body,
    )


def _text_rowids_and_indexed_ids(path: Path) -> tuple[list[int], list[int]]:
    """The FTS5 rowids and the ids of the indexed (not skipped) document rows, sorted."""
    connection = sqlite3.connect(path)
    try:
        rowids = [row[0] for row in connection.execute("SELECT rowid FROM knowledge_text")]
        ids = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM knowledge_documents WHERE sha256 IS NOT NULL"
            )
        ]
    finally:
        connection.close()
    return sorted(rowids), sorted(ids)


def test_finds_fts5_when_interpreter_sqlite_has_it() -> None:
    assert fts5_available()


def test_raises_fts5_error_when_sqlite_lacks_module(tmp_path: Path) -> None:
    path = tmp_path / "data" / "events.db"

    with pytest.raises(Fts5UnavailableError):
        open_knowledge_index(path, connect=_connect_without_fts5)

    assert not path.exists()
    assert not path.parent.exists()


def test_raises_storage_error_when_database_unusable(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    path.mkdir()

    with pytest.raises(StorageError):
        open_knowledge_index(path)


def test_finds_inflected_word_when_porter_stems(tmp_path: Path) -> None:
    index = open_knowledge_index(tmp_path / "events.db")
    document = _document("brain/playbooks/cleanup.md", "remove the worktrees after merge")
    index.apply(HUB, IndexChange(version=INDEX_VERSION, documents=(document,)))

    hits = index.search(HUB, ("worktree",), limit=MAX_RESULTS)

    assert [hit.path for hit in hits] == [document.path]


def test_cuts_snippet_to_one_line_when_body_long(tmp_path: Path) -> None:
    index = open_knowledge_index(tmp_path / "events.db")
    lines = [" ".join(f"word{line}x{n}" for n in range(10)) for line in range(30)]
    lines[15] = "the marker stands right in the middle of this line"
    body = "\n".join(lines)
    assert len(body.split()) == 300
    index.apply(
        HUB, IndexChange(version=INDEX_VERSION, documents=(_document("brain/long.md", body),))
    )

    (hit,) = index.search(HUB, ("marker",), limit=MAX_RESULTS)

    assert "\n" not in hit.snippet
    assert "\r" not in hit.snippet
    assert len(hit.snippet) <= MAX_SNIPPET_CHARS
    assert "marker" in hit.snippet


def test_pairs_text_with_indexed_rows_when_rows_dropped_and_hub_rebuilt(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    index = open_knowledge_index(path)
    first = tuple(_document(f"brain/{name}.md", f"{name} text") for name in ("a", "b", "c", "d"))
    index.apply("/hubs/other", IndexChange(version=INDEX_VERSION, documents=first[:1]))
    index.apply(HUB, IndexChange(version=INDEX_VERSION, documents=first))

    # c and d hold the highest ids: once their rows go, SQLite gives a freed id to e.
    skipped = (
        SkippedFile(path="brain/b.md", fingerprint=first[1].fingerprint, reason="not UTF-8"),
        SkippedFile(path="brain/c.md", fingerprint=None, reason="cannot be read"),
    )
    index.apply(HUB, IndexChange(version=INDEX_VERSION, skipped=skipped, dropped=("brain/d.md",)))
    index.apply(
        HUB, IndexChange(version=INDEX_VERSION, documents=(_document("brain/e.md", "e text"),))
    )

    rowids, ids = _text_rowids_and_indexed_ids(path)
    assert rowids == ids
    assert [hit.path for hit in index.search(HUB, ("d",), limit=MAX_RESULTS)] == []
    assert [hit.path for hit in index.search(HUB, ("e",), limit=MAX_RESULTS)] == ["brain/e.md"]

    rebuilt = (_document("brain/f.md", "f text"), _document("brain/a.md", "g text"))
    index.apply(HUB, IndexChange(version=INDEX_VERSION, rebuild=True, documents=rebuilt))

    rowids, ids = _text_rowids_and_indexed_ids(path)
    assert rowids == ids
    assert [hit.path for hit in index.search(HUB, ("a",), limit=MAX_RESULTS)] == []
    assert [hit.path for hit in index.search(HUB, ("g",), limit=MAX_RESULTS)] == ["brain/a.md"]
    other = index.search("/hubs/other", ("a",), limit=MAX_RESULTS)
    assert [hit.path for hit in other] == ["brain/a.md"]


def _rows_per_path(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT path, COUNT(*) FROM knowledge_documents WHERE hub = ? GROUP BY path", (HUB,)
        ).fetchall()
    finally:
        connection.close()
    return dict(rows)


def _a_checkout(before_read: Callable[[str], None] | None = None) -> FakeKnowledgeCheckout:
    checkout = FakeKnowledgeCheckout(before_read=before_read)
    for name in ("a", "b", "c"):
        checkout.write(f"brain/playbooks/{name}.md", f"marker {name}".encode())
    return checkout


def _listed_paths(checkout: FakeKnowledgeCheckout) -> list[str]:
    return [file.path for file in checkout.listed()]


def test_reads_every_file_when_stored_version_older(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    index = open_knowledge_index(path)
    checkout = _a_checkout()
    sync_knowledge(index, checkout, HUB)
    connection = sqlite3.connect(path)
    try:
        with connection:
            connection.execute("UPDATE knowledge_documents SET index_version = ?", (0,))
    finally:
        connection.close()

    report = sync_knowledge(index, checkout, HUB)

    assert report.read == report.listed == 3
    assert index.stored(HUB).version == INDEX_VERSION
    assert _rows_per_path(path) == dict.fromkeys(_listed_paths(checkout), 1)
    assert len(index.search(HUB, ("marker",), limit=MAX_RESULTS)) == 3


def test_keeps_one_row_per_file_when_syncs_run_concurrently(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    barrier = threading.Barrier(2)
    armed = threading.Event()

    def meet(_: str) -> None:
        # Both syncs have planned the same read before either writes.
        if armed.is_set():
            barrier.wait(timeout=10)

    checkout = _a_checkout(meet)
    sync_knowledge(open_knowledge_index(path), checkout, HUB)
    checkout.write("brain/playbooks/b.md", b"marker changed")
    indexes = (open_knowledge_index(path), open_knowledge_index(path))

    armed.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = [pool.submit(sync_knowledge, index, checkout, HUB) for index in indexes]
        reports = [future.result(timeout=30) for future in running]

    assert [(report.read, report.indexed) for report in reports] == [(1, 1), (1, 1)]
    assert _rows_per_path(path) == dict.fromkeys(_listed_paths(checkout), 1)
    rowids, ids = _text_rowids_and_indexed_ids(path)
    assert rowids == ids
    hits = indexes[0].search(HUB, ("changed",), limit=MAX_RESULTS)
    assert [hit.path for hit in hits] == ["brain/playbooks/b.md"]


NOW: Final = "brain/now.md"
CLEANUP: Final = "brain/playbooks/c.md"


def _a_linked_checkout(before_read: Callable[[str], None] | None = None) -> FakeKnowledgeCheckout:
    checkout = FakeKnowledgeCheckout(before_read=before_read)
    checkout.write("brain/playbooks/a.md", b"marker a, see [now](../now.md)")
    checkout.write("brain/playbooks/b.md", b"marker b, see [now](../now.md) and [c](c.md)")
    checkout.write(CLEANUP, b"marker c")
    return checkout


def _backlinks(index: SqliteKnowledgeIndex, target: str) -> list[str]:
    return [item.path for item in index.backlinks(HUB, target, limit=MAX_BACKLINKS).items]


def _rows_per_link(path: Path) -> dict[tuple[str, str], int]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT source, target, COUNT(*) FROM knowledge_links WHERE hub = ? "
            "GROUP BY source, target",
            (HUB,),
        ).fetchall()
    finally:
        connection.close()
    return {(source, target): count for source, target, count in rows}


def test_rebuilds_links_when_stored_version_older(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    index = open_knowledge_index(path)
    checkout = _a_linked_checkout()
    sync_knowledge(index, checkout, HUB)
    connection = sqlite3.connect(path)
    try:
        with connection:
            # A hub indexed before links were stored: version 1 rows, no link rows.
            connection.execute("UPDATE knowledge_documents SET index_version = ?", (1,))
            connection.execute("DELETE FROM knowledge_links")
    finally:
        connection.close()
    assert _backlinks(index, NOW) == []

    report = sync_knowledge(index, checkout, HUB)

    assert report.read == report.listed == 3
    assert index.stored(HUB).version == INDEX_VERSION == 2
    assert _backlinks(index, NOW) == ["brain/playbooks/a.md", "brain/playbooks/b.md"]
    assert _backlinks(index, CLEANUP) == ["brain/playbooks/b.md"]


def test_converges_links_when_syncs_run_concurrently(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    barrier = threading.Barrier(2)
    armed = threading.Event()

    def meet(_: str) -> None:
        # Both syncs have planned the same reads before either writes.
        if armed.is_set():
            barrier.wait(timeout=10)

    checkout = _a_linked_checkout(meet)
    sync_knowledge(open_knowledge_index(path), checkout, HUB)
    expected = {
        ("brain/playbooks/a.md", NOW): 1,
        ("brain/playbooks/b.md", NOW): 1,
        ("brain/playbooks/b.md", CLEANUP): 1,
    }
    assert _rows_per_link(path) == expected
    checkout.write("brain/playbooks/b.md", b"marker changed, see [now](../now.md) and [c](c.md)")
    indexes = (open_knowledge_index(path), open_knowledge_index(path))

    armed.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = [pool.submit(sync_knowledge, index, checkout, HUB) for index in indexes]
        reports = [future.result(timeout=30) for future in running]
    synced = _rows_per_link(path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = [
            pool.submit(sync_knowledge, index, checkout, HUB, rebuild=True) for index in indexes
        ]
        rebuilt = [future.result(timeout=30) for future in running]

    assert [(report.read, report.indexed) for report in reports] == [(1, 1), (1, 1)]
    assert [(report.read, report.indexed) for report in rebuilt] == [(3, 3), (3, 3)]
    assert synced == expected
    assert _rows_per_link(path) == expected
    assert _backlinks(indexes[0], NOW) == ["brain/playbooks/a.md", "brain/playbooks/b.md"]
    assert _backlinks(indexes[1], CLEANUP) == ["brain/playbooks/b.md"]


def test_drops_rows_and_text_when_paths_exceed_sql_variable_limit(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    index = open_knowledge_index(path)
    paths = [f"brain/many/{number:05}.md" for number in range(_OVER_VARIABLE_LIMIT)]
    connection = sqlite3.connect(path)
    try:
        with connection:
            # Written directly: 33,000 applies would make the test slow.
            connection.executemany(
                "INSERT INTO knowledge_documents (hub, path, kind, title, size, mtime_ns, "
                "sha256, index_version) VALUES (?, ?, 'doc', 'Many', 1, 1, ?, ?)",
                [(HUB, name, "0" * 64, INDEX_VERSION) for name in paths],
            )
            connection.execute(
                "INSERT INTO knowledge_text (rowid, title, body) "
                "SELECT id, title, 'many words' FROM knowledge_documents"
            )
    finally:
        connection.close()
    kept = _document("brain/kept.md", "kept words")
    index.apply(HUB, IndexChange(version=INDEX_VERSION, documents=(kept,)))

    index.apply(HUB, IndexChange(version=INDEX_VERSION, dropped=tuple(paths)))

    assert list(index.stored(HUB).files) == [kept.path]
    rowids, ids = _text_rowids_and_indexed_ids(path)
    assert rowids == ids
    assert len(ids) == 1
    assert [hit.path for hit in index.search(HUB, ("words",), limit=MAX_RESULTS)] == [kept.path]


def test_keeps_rows_unchanged_when_change_fails_partway(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    index = open_knowledge_index(path)
    first = (_document("brain/a.md", "alpha"), _document("brain/b.md", "beta"))
    index.apply(HUB, IndexChange(version=INDEX_VERSION, documents=first))
    connection = sqlite3.connect(path)
    try:
        with connection:
            connection.execute(
                "CREATE TRIGGER refuse_c BEFORE INSERT ON knowledge_documents "
                "WHEN NEW.path = 'brain/c.md' BEGIN SELECT RAISE(ABORT, 'refused'); END"
            )
    finally:
        connection.close()
    before = index.stored(HUB)
    # a.md is rewritten before c.md's insert fails; b.md would be dropped after it.
    change = IndexChange(
        version=INDEX_VERSION,
        documents=(_document("brain/a.md", "gamma"), _document("brain/c.md", "delta")),
        dropped=("brain/b.md",),
    )

    with pytest.raises(DatabaseAccessError) as raised:
        index.apply(HUB, change)

    assert "gamma" not in str(raised.value)
    assert "delta" not in str(raised.value)
    assert index.stored(HUB) == before
    for word, paths in (("alpha", ["brain/a.md"]), ("beta", ["brain/b.md"]), ("gamma", [])):
        assert [hit.path for hit in index.search(HUB, (word,), limit=MAX_RESULTS)] == paths
    rowids, ids = _text_rowids_and_indexed_ids(path)
    assert rowids == ids


def _linked(path: str, *targets: str) -> IndexedDocument:
    return _document(path, f"{path} text").model_copy(update={"links": targets})


def test_deletes_link_rows_when_path_dropped_or_hub_rebuilt(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    index = open_knowledge_index(path)
    documents = (
        _linked("brain/a.md", "brain/now.md"),
        _linked("brain/b.md", "brain/now.md", "brain/x.md"),
        _linked("brain/c.md", "brain/now.md"),
    )
    index.apply(HUB, IndexChange(version=INDEX_VERSION, documents=documents))
    index.apply("/hubs/other", IndexChange(version=INDEX_VERSION, documents=documents[:1]))

    index.apply(HUB, IndexChange(version=INDEX_VERSION, dropped=("brain/b.md",)))
    after_drop = _rows_per_link(path)
    index.apply(HUB, IndexChange(version=INDEX_VERSION, rebuild=True, documents=documents[:1]))

    assert after_drop == {("brain/a.md", "brain/now.md"): 1, ("brain/c.md", "brain/now.md"): 1}
    assert _rows_per_link(path) == {("brain/a.md", "brain/now.md"): 1}
    assert index.backlinks("/hubs/other", "brain/now.md", limit=MAX_BACKLINKS).total == 1


def test_searches_link_index_when_backlinks_read(tmp_path: Path) -> None:
    """The page and the count each seek ``(hub, target)`` in the links' covering index, the
    page in its ``source`` order: neither scans the hub's documents or links, nor sorts."""
    path = tmp_path / "events.db"
    index = open_knowledge_index(path)
    documents = tuple(_linked(f"brain/{name}.md", "brain/now.md") for name in "abc")
    index.apply(HUB, IndexChange(version=INDEX_VERSION, documents=documents))
    statements: list[tuple[str, object]] = []

    def record(*args: object) -> None:
        statements.append((str(args[2]), args[3]))

    event.listen(Engine, "before_cursor_execute", record)
    try:
        found = index.backlinks(HUB, "brain/now.md", limit=2)
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    connection = sqlite3.connect(path)
    try:
        plans = [
            [row[3] for row in connection.execute(f"EXPLAIN QUERY PLAN {sql}", parameters)]
            for sql, parameters in statements
            if "knowledge_links" in sql
        ]
    finally:
        connection.close()

    assert [item.path for item in found.items] == ["brain/a.md", "brain/b.md"]
    assert len(plans) == 2
    seek = (
        "SEARCH knowledge_links USING COVERING INDEX ix_knowledge_links_hub_target "
        "(hub=? AND target=?)"
    )
    for plan in plans:
        assert plan[0] == seek
        assert not any("SCAN" in step or "TEMP B-TREE" in step for step in plan)
