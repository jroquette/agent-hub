"""The ``ItemVersionStore`` contract suite: the in-memory fake and the SQLite store honour it.

An implementation's ``tests/contract/`` provides an ``item_version_store`` fixture (an empty
store) and declares ``class Test<Implementation>(ItemVersionStoreContract)``. Checks raise
``AssertionError`` by hand: core ships this suite without depending on pytest.
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

from agent_hub.core.item_versions.item_version import (
    ItemVersion,
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

T0 = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
AGENT: Final = "plugin/demo/agents/reviewer.md"
OTHER_AGENT: Final = "plugin/demo/agents/planner.md"
AUTHOR = VersionAuthor(name="Jane Doe", email="jane@example.com")
_RACERS: Final = 8
_WRITE_VERBS: Final = ("update", "delete", "remove", "purge", "replace", "set", "clear", "drop")


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


def _new(seq: int, *, project: str = "demo", unit_path: str = AGENT) -> NewItemVersion:
    content = f"---\nname: reviewer\n---\nVersion {seq} of {unit_path}.\n".encode()
    published = seq % 2 == 0
    return NewItemVersion(
        project=project,
        unit_path=unit_path,
        kind=UnitKind.AGENT,
        seq=seq,
        origin=VersionOrigin.PUBLISH if published else VersionOrigin.EXTERNAL,
        first=seq == 1,
        author=AUTHOR if published else None,
        recorded_at=T0 + timedelta(minutes=seq),
        content_hash=file_hash(content),
        size=len(content),
        draft_id="agent-a1b2c3" if published else None,
        content=content,
    )


def _append(store: ItemVersionStore, count: int, **unit: str) -> list[ItemVersion]:
    return [store.append(_new(seq, **unit)) for seq in range(1, count + 1)]


def _refused(store: ItemVersionStore, version: NewItemVersion) -> ItemVersionSequenceError | None:
    try:
        store.append(version)
    except ItemVersionSequenceError as error:
        return error
    return None


class ItemVersionStoreContract:
    """Append gap-free, last, newest-first pages with a cursor, scoped get, append-only."""

    def test_appends_and_reads_last_when_versions_appended(
        self, item_version_store: ItemVersionStore
    ) -> None:
        _check(item_version_store.last("demo", AGENT) is None, "a unit with no version: None")
        new = _new(1)

        stored = item_version_store.append(new)
        second = item_version_store.append(_new(2))

        _check(uuid.UUID(stored.id).version == 7, f"the store mints a UUIDv7: {stored.id}")
        _check(stored.id != second.id, "every version has its own id")
        _check(
            stored.model_dump(exclude={"id"}) == new.model_dump(),
            "the appended version keeps every field given",
        )
        _check(item_version_store.last("demo", AGENT) == second.meta(), "last is the newest")
        _check(second.draft_id == "agent-a1b2c3", "a publish keeps its draft id")
        _check(item_version_store.last("demo", OTHER_AGENT) is None, "last is per unit")
        _check(item_version_store.last("other", AGENT) is None, "last is per project")

    def test_lists_newest_first_with_cursor_when_paged(
        self, item_version_store: ItemVersionStore
    ) -> None:
        stored = _append(item_version_store, 5)
        _append(item_version_store, 2, unit_path=OTHER_AGENT)
        _append(item_version_store, 2, project="other")
        store = item_version_store

        pages = [
            store.page("demo", AGENT, limit=2),
            store.page("demo", AGENT, limit=2, before_seq=4),
            store.page("demo", AGENT, limit=2, before_seq=2),
            store.page("demo", AGENT, limit=2, before_seq=1),
        ]

        seqs = [[version.seq for version in page] for page in pages]
        _check(seqs == [[5, 4], [3, 2], [1], []], f"newest first, below the cursor: {seqs}")
        everything = store.page("demo", AGENT)
        expected = tuple(version.meta() for version in reversed(stored))
        _check(everything == expected, "a page holds the versions without their content")

    def test_gets_version_when_id_in_unit(self, item_version_store: ItemVersionStore) -> None:
        first, second = _append(item_version_store, 2)

        _check(item_version_store.get("demo", AGENT, first.id) == first, "the first, with content")
        _check(item_version_store.get("demo", AGENT, second.id) == second, "the second too")

    def test_answers_none_when_id_in_other_unit(self, item_version_store: ItemVersionStore) -> None:
        (version,) = _append(item_version_store, 1)
        _append(item_version_store, 1, unit_path=OTHER_AGENT)
        _append(item_version_store, 1, project="other")
        unknown = "0199f0a0-0000-7000-8000-0000000000ff"

        store = item_version_store
        _check(store.get("demo", OTHER_AGENT, version.id) is None, "another unit: None")
        _check(store.get("other", AGENT, version.id) is None, "another project: None")
        _check(store.get("demo", AGENT, unknown) is None, "an unknown id: None")

    def test_refuses_append_when_sequence_not_next(
        self, item_version_store: ItemVersionStore
    ) -> None:
        _append(item_version_store, 2)

        for seq in (1, 2, 4):
            error = _refused(item_version_store, _new(seq))
            if error is None:
                raise AssertionError(f"seq {seq} after 2 must be refused")
            _check((error.expected, error.got) == (3, seq), f"expected 3, got {seq}: {error}")
        _check(_refused(item_version_store, _new(2, unit_path=OTHER_AGENT)) is not None, "gap")
        _check(len(item_version_store.page("demo", AGENT)) == 2, "a refused append writes nothing")
        _check(item_version_store.last("demo", OTHER_AGENT) is None, "nor in the other unit")

        # Writers that all read "no version yet" race for seq 1: exactly one wins.
        outcomes: list[bool] = []
        start = threading.Barrier(_RACERS)

        def race() -> None:
            start.wait()
            outcomes.append(_refused(item_version_store, _new(1, project="race")) is None)

        racers = [threading.Thread(target=race) for _ in range(_RACERS)]
        for racer in racers:
            racer.start()
        for racer in racers:
            racer.join()
        _check(outcomes.count(True) == 1, f"one racer stores seq 1: {outcomes}")
        _check(len(item_version_store.page("race", AGENT)) == 1, "one version was stored")

    def test_has_no_update_or_delete_when_port_inspected(
        self, item_version_store: ItemVersionStore
    ) -> None:
        port = {name for name in vars(ItemVersionStore) if not name.startswith("_")}
        _check(port == {"append", "last", "page", "get"}, f"the port is append and reads: {port}")
        writes = [
            name
            for name in dir(item_version_store)
            if not name.startswith("_") and name.startswith(_WRITE_VERBS)
        ]
        _check(not writes, f"the store offers no update or delete: {writes}")
