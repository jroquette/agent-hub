import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import Engine, event

from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions, UnitState
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import (
    NewItemVersion,
    UnitKind,
    VersionAuthor,
    VersionOrigin,
)
from agent_hub.core.item_versions.unit_hash import file_hash
from agent_hub.core.item_versions.version_store import (
    ItemVersionSequenceError,
    ItemVersionStore,
)
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.storage.item_version_store import open_item_version_store

T0 = datetime(2026, 10, 17, 9, 0, 0, 123456, tzinfo=UTC)
AGENT: Final = "plugin/demo/agents/reviewer.md"
CONTENT: Final = b"---\nname: reviewer\n---\nReview the diff.\n"
READERS: Final = 10
HUB: Final = "/hubs/demo-hub"
WAIT_SECONDS: Final = 30.0


def _version(seq: int, content: bytes = CONTENT) -> NewItemVersion:
    return NewItemVersion(
        project="demo",
        unit_path=AGENT,
        kind=UnitKind.AGENT,
        seq=seq,
        origin=VersionOrigin.EXTERNAL,
        first=seq == 1,
        recorded_at=T0,
        content_hash=file_hash(content),
        size=len(content),
        content=content,
    )


def _capture(store: ItemVersionStore, content: bytes) -> Mapping[str, UnitState]:
    """One reader's capture of the agent (its own ``CaptureItemVersions``, so no memo is
    shared and every reader reaches the store)."""
    reader = FakeHubFileReader({HUB: FakeHub(skill_files={AGENT: content})})
    unit = ItemUnit(project="demo", unit_path=AGENT, kind=UnitKind.AGENT)
    return CaptureItemVersions(store, reader, lambda: T0).capture("demo", HUB, [(unit, "mark")])


@contextmanager
def _statements() -> Iterator[list[str]]:
    """Every SQL statement any engine sends while the block runs."""
    seen: list[str] = []

    def record(*args: Any) -> None:
        seen.append(str(args[2]))

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def test_stores_one_version_when_concurrent_append_races(tmp_path: Path) -> None:
    store = open_item_version_store(tmp_path / "events.db")
    errors: list[BaseException] = []
    states: list[Mapping[str, UnitState]] = []
    start = threading.Barrier(READERS, timeout=WAIT_SECONDS)

    def read() -> None:
        start.wait()
        try:
            states.append(_capture(store, CONTENT))
        except BaseException as error:  # noqa: BLE001 -- every failure is checked below
            errors.append(error)

    readers = [threading.Thread(target=read, daemon=True) for _ in range(READERS)]
    for reader in readers:
        reader.start()
    for reader in readers:
        reader.join(WAIT_SECONDS)

    assert not any(reader.is_alive() for reader in readers)
    assert errors == []
    assert states == [{AGENT: UnitState.OK}] * READERS
    stored = store.page("demo", AGENT)
    assert [(version.seq, version.content_hash) for version in stored] == [(1, file_hash(CONTENT))]


def test_issues_no_update_or_delete_when_append_only_store_used(tmp_path: Path) -> None:
    store = open_item_version_store(tmp_path / "events.db")
    author = VersionAuthor(name="Jane Doe", email="jane@example.com")
    edited = b"---\nname: reviewer\n---\nReview the diff twice.\n"

    with _statements() as seen:
        first = store.append(_version(1))
        store.append(
            _version(2, edited).model_copy(
                update={"origin": VersionOrigin.PUBLISH, "author": author}
            )
        )
        store.last("demo", AGENT)
        store.page("demo", AGENT, limit=1, before_seq=2)
        store.get("demo", AGENT, first.id)
        with suppress(ItemVersionSequenceError):
            store.append(_version(2))

    on_table = [sql for sql in seen if "item_versions" in sql]
    assert any(sql.lstrip().upper().startswith("INSERT") for sql in on_table)
    writes = [sql for sql in on_table if sql.lstrip().upper().startswith(("UPDATE", "DELETE"))]
    assert writes == []
