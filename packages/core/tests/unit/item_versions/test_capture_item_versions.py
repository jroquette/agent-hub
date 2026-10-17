"""Capture on read (AGH-295, D2, D9, D17, D20, O4): a unit seen for the first time gets its
``first`` baseline, a changed one an ``external`` version, an unchanged stat mark reads nothing,
a lost race stores one row, a failed store or a spent budget leaves the unit for the next read,
and a secret or too-large unit is never stored."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final

import pytest

from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions, UnitState
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import (
    ItemVersion,
    NewItemVersion,
    UnitKind,
    VersionOrigin,
)
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile, encode
from agent_hub.core.item_versions.unit_hash import file_hash, folder_hash
from agent_hub.core.item_versions.version_store import (
    ItemVersionSequenceError,
    ItemVersionStore,
)
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.core.testing.item_version_fakes import InMemoryItemVersionStore

HUB: Final = "/hubs/demo-hub"
PROJECT: Final = "demo"
NOW: Final = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
AGENT: Final = "plugin/demo/agents/scout.md"
SKILL: Final = "plugin/demo/skills/alpha"
SCOUT: Final = b"---\nname: scout\ndescription: Scouts.\n---\nScout the repo.\n"
ALPHA: Final = b"---\nname: alpha\ndescription: Alpha.\n---\n# Alpha\n"
REFERENCE: Final = b"# R\n"
# A synthetic GitHub token, built from fragments so no format-valid secret is one literal.
SYNTHETIC_TOKEN: Final = "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def _agent() -> ItemUnit:
    return ItemUnit(project=PROJECT, unit_path=AGENT, kind=UnitKind.AGENT)


def _skill() -> ItemUnit:
    return ItemUnit(project=PROJECT, unit_path=SKILL, kind=UnitKind.SKILL)


def _rig(
    files: Mapping[str, bytes],
    *,
    store: ItemVersionStore | None = None,
    budget: int | None = None,
) -> tuple[CaptureItemVersions, FakeHubFileReader, FakeHub, InMemoryItemVersionStore]:
    hub = FakeHub(skill_files=dict(files))
    reader = FakeHubFileReader({HUB: hub})
    memory = InMemoryItemVersionStore()
    options = {} if budget is None else {"budget_bytes": budget}
    capture = CaptureItemVersions(
        memory if store is None else store,
        reader,
        lambda: NOW,
        **options,
    )
    return capture, reader, hub, memory


def _stored(store: InMemoryItemVersionStore, unit_path: str) -> list[tuple[int, str, bool]]:
    return [
        (version.seq, version.content_hash, version.first)
        for version in reversed(store.page(PROJECT, unit_path))
    ]


def test_records_baseline_when_unit_first_seen() -> None:
    capture, _, _, store = _rig(
        {AGENT: SCOUT, f"{SKILL}/SKILL.md": ALPHA, f"{SKILL}/references/r.md": REFERENCE}
    )

    states = capture.capture(PROJECT, HUB, [(_agent(), ("a", 1)), (_skill(), ("s", 1))])

    assert states == {AGENT: UnitState.OK, SKILL: UnitState.OK}
    agent = store.last(PROJECT, AGENT)
    assert agent is not None
    assert (agent.origin, agent.first, agent.author, agent.kind) == (
        VersionOrigin.EXTERNAL,
        True,
        None,
        UnitKind.AGENT,
    )
    assert (agent.content_hash, agent.size) == (file_hash(SCOUT), len(SCOUT))
    assert agent.recorded_at == NOW
    skill = store.get(PROJECT, SKILL, store.page(PROJECT, SKILL)[0].id)
    assert skill is not None
    files = UnitContent(
        files=(
            UnitFile(path="SKILL.md", content=ALPHA),
            UnitFile(path="references/r.md", content=REFERENCE),
        )
    )
    assert skill.content_hash == folder_hash(files.files)
    assert skill.content == encode(files, folder=True)
    assert skill.size == len(ALPHA) + len(REFERENCE)


def test_adds_nothing_when_mark_unchanged() -> None:
    capture, reader, hub, store = _rig({AGENT: SCOUT})
    capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])
    reads = len(reader.unit_reads)
    hub.skill_files[AGENT] = b"---\nname: scout\n---\nEdited, same mark.\n"

    states = capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])

    assert states == {AGENT: UnitState.OK}
    assert len(reader.unit_reads) == reads
    assert _stored(store, AGENT) == [(1, file_hash(SCOUT), True)]


def test_records_change_when_mark_and_content_differ() -> None:
    capture, _, hub, store = _rig({AGENT: SCOUT})
    capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])
    edited = b"---\nname: scout\n---\nEdited.\n"
    hub.skill_files[AGENT] = edited
    capture.capture(PROJECT, HUB, [(_agent(), ("a", 2))])
    # A new mark over the same bytes (an mtime-only touch) reads but stores nothing.
    capture.capture(PROJECT, HUB, [(_agent(), ("a", 3))])

    assert _stored(store, AGENT) == [(1, file_hash(SCOUT), True), (2, file_hash(edited), False)]


class _RacedStore(InMemoryItemVersionStore):
    """Another reader stores the same content just before this one's first append."""

    def __init__(self) -> None:
        super().__init__()
        self.appends = 0

    def append(self, version: NewItemVersion) -> ItemVersion:
        self.appends += 1
        if self.appends == 1:
            super().append(version)
        return super().append(version)


def test_records_one_version_when_race_lost() -> None:
    store = _RacedStore()
    capture, _, _, _ = _rig({AGENT: SCOUT}, store=store)

    states = capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])

    assert states == {AGENT: UnitState.OK}
    assert _stored(store, AGENT) == [(1, file_hash(SCOUT), True)]


class _AlwaysLostStore(InMemoryItemVersionStore):
    def append(self, version: NewItemVersion) -> ItemVersion:
        raise ItemVersionSequenceError(
            version.project, version.unit_path, expected=version.seq + 1, got=version.seq
        )


def test_retries_next_read_when_race_lost_every_try() -> None:
    capture, reader, _, _ = _rig({AGENT: SCOUT}, store=_AlwaysLostStore())

    capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])
    capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])

    assert len(reader.unit_reads) == 2


class _BusyError(Exception):
    """Stands in for the database's busy error."""


class _FailingOnceStore(InMemoryItemVersionStore):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def append(self, version: NewItemVersion) -> ItemVersion:
        if not self.failed:
            self.failed = True
            raise _BusyError
        return super().append(version)


def test_retries_next_read_when_store_fails() -> None:
    store = _FailingOnceStore()
    capture, _, _, _ = _rig({AGENT: SCOUT}, store=store)

    with pytest.raises(_BusyError):
        capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])
    states = capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])

    assert states == {AGENT: UnitState.OK}
    assert _stored(store, AGENT) == [(1, file_hash(SCOUT), True)]


def test_captures_rest_next_read_when_budget_spent() -> None:
    other = "plugin/demo/agents/other.md"
    capture, _, _, store = _rig({AGENT: SCOUT, other: SCOUT}, budget=len(SCOUT))
    second = ItemUnit(project=PROJECT, unit_path=other, kind=UnitKind.AGENT)
    units = [(_agent(), ("a", 1)), (second, ("o", 1))]

    first_states = capture.capture(PROJECT, HUB, units)
    assert first_states == {AGENT: UnitState.OK}
    assert store.last(PROJECT, other) is None

    next_states = capture.capture(PROJECT, HUB, units)
    assert next_states == {AGENT: UnitState.OK, other: UnitState.OK}
    assert _stored(store, other) == [(1, file_hash(SCOUT), True)]


def test_stores_nothing_when_secret_or_too_large() -> None:
    big = "plugin/demo/agents/big.md"
    secret = f"---\nname: scout\n---\nexport GH_TOKEN={SYNTHETIC_TOKEN}\n".encode()
    capture, reader, _, store = _rig({AGENT: secret, big: b"x" * (MAX_SKILL_FILE_BYTES + 1)})
    large = ItemUnit(project=PROJECT, unit_path=big, kind=UnitKind.AGENT)
    units = [(_agent(), ("a", 1)), (large, ("b", 1))]

    states = capture.capture(PROJECT, HUB, units)
    reads = len(reader.unit_reads)
    again = capture.capture(PROJECT, HUB, units)

    assert states == again == {AGENT: UnitState.SECRET, big: UnitState.TOO_LARGE}
    assert store.last(PROJECT, AGENT) is None
    assert store.last(PROJECT, big) is None
    # The state is kept with the mark: an unchanged unit is not read again.
    assert len(reader.unit_reads) == reads


def test_reports_unreadable_when_unit_is_special() -> None:
    capture, _, hub, store = _rig({})
    hub.skill_specials = frozenset({AGENT})

    states = capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])

    assert states == {AGENT: UnitState.UNREADABLE}
    assert store.last(PROJECT, AGENT) is None


def test_skips_unit_when_gone_before_read() -> None:
    capture, reader, _, store = _rig({})

    states = capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])
    capture.capture(PROJECT, HUB, [(_agent(), ("a", 1))])

    assert states == {}
    assert store.last(PROJECT, AGENT) is None
    assert len(reader.unit_reads) == 2
