"""The shared write step (AGH-295, S4, D3, D9, D12, D22, O2, O6, A1, A2): it records the disk's
content as ``external`` first when it differs from the last version, writes, then records the
new version; it refuses before writing (read-only hub, no author, a link, an unreadable unit, a
managed unit without confirmation), writes nothing when the content is equal, records nothing
more when the write fails, and never stores secret or too-large content. A Publish of a draft
some version already names as its ``publish`` is refused under the lock, before any read (A20)."""

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

import pytest

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry
from agent_hub.core.hubs.hub_registry import UnreadUnit
from agent_hub.core.item_versions.append_version import ATTEMPTS
from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.item_versions.hub_item_writer import (
    HubItemWriteError,
    ItemWriteRefusedError,
    rollback_failed,
)
from agent_hub.core.item_versions.item_units import ItemUnit, unit_parts
from agent_hub.core.item_versions.item_version import (
    ItemVersion,
    NewItemVersion,
    UnitKind,
    VersionAuthor,
    VersionOrigin,
)
from agent_hub.core.item_versions.publish_rules import Destination
from agent_hub.core.item_versions.record_and_write import (
    ItemWrittenRaceLostError,
    ItemWrittenUnrecordedError,
    NoAuthor,
    Placement,
    RecordAndWrite,
    UnitReads,
)
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.item_versions.unit_hash import file_hash
from agent_hub.core.item_versions.version_store import ItemVersionSequenceError
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES, SkillPathError
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.core.testing.item_version_fakes import FakeHubItemWriter, InMemoryItemVersionStore
from agent_hub.core.testing.skill_trees import FIXTURE_PLATFORM_VERSION

HUB: Final = "/hubs/demo-hub"
PROJECT: Final = "demo"
NOW: Final = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
AGENT: Final = "plugin/demo/agents/scout.md"
HOOKS: Final = ".claude/settings.json"
SCOUT: Final = b"---\nname: scout\ndescription: Scouts.\n---\nScout the repo.\n"
EDITED: Final = b"---\nname: scout\ndescription: Scouts.\n---\nEdited by hand.\n"
NEWER: Final = b"---\nname: scout\ndescription: Scouts.\n---\nPublished.\n"
AUTHOR: Final = VersionAuthor(name="Dev One", email="dev@example.com")
WAIT_SECONDS: Final = 10.0
# How long a write is given to land while a capture of its unit is held.
INTERLEAVE_SECONDS: Final = 0.3
# A synthetic GitHub token, built from fragments so no format-valid secret is one literal.
SYNTHETIC_TOKEN: Final = "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"

type AuthorOf = Callable[[str], VersionAuthor | NoAuthor]


class _Rig:
    """The step over one fake hub shared by the reader and the writer, with its capture."""

    def __init__(
        self,
        files: dict[str, bytes],
        *,
        author_of: AuthorOf | None = None,
        reader: FakeHubFileReader | None = None,
    ) -> None:
        self.hub = FakeHub(skill_files=dict(files))
        self.reader = reader if reader is not None else FakeHubFileReader({HUB: self.hub})
        self.reader.hubs[HUB] = self.hub
        self.writer = FakeHubItemWriter({HUB: self.hub})
        self.store = InMemoryItemVersionStore()
        self.capture = CaptureItemVersions(self.store, self.reader, lambda: NOW)
        self.step = RecordAndWrite(
            self.store,
            reader=self.reader,
            writer=self.writer,
            author_of=author_of if author_of is not None else (lambda _project: AUTHOR),
            clock=lambda: NOW,
            capture=self.capture,
        )

    def seen(self, mark: object) -> None:
        """A catalog read of the agent under ``mark``."""
        self.capture.capture(PROJECT, HUB, [(_agent(), mark)])

    def origins(self, unit_path: str = AGENT) -> list[tuple[VersionOrigin, str]]:
        return [
            (version.origin, version.content_hash)
            for version in reversed(self.store.page(PROJECT, unit_path))
        ]


def _agent() -> ItemUnit:
    return ItemUnit(project=PROJECT, unit_path=AGENT, kind=UnitKind.AGENT)


def _file(name: str, content: bytes) -> UnitContent:
    return UnitContent(files=(UnitFile(path=name, content=content),))


def _scout(content: bytes) -> UnitContent:
    return _file("scout.md", content)


def _managed(rig: _Rig, path: str) -> None:
    entry = ManagedFileEntry(ownership="managed", sha256="ab" * 32, executable=False)
    rig.hub.lock = HubLock(
        lock_version=1,
        platform_version=FIXTURE_PLATFORM_VERSION,
        schema_version=1,
        modules=(),
        files={path: entry},
    )


def test_records_external_first_when_disk_differs() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.seen(1)
    first = rig.store.last(PROJECT, AGENT)
    assert first is not None
    rig.hub.skill_files[AGENT] = EDITED

    result = rig.step.write(
        HUB, _agent(), _scout(SCOUT), origin=VersionOrigin.RESTORE, restored_from=first.id
    )

    assert rig.hub.skill_files[AGENT] == SCOUT
    assert rig.origins() == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT)),
        (VersionOrigin.EXTERNAL, file_hash(EDITED)),
        (VersionOrigin.RESTORE, file_hash(SCOUT)),
    ]
    assert (result.changed, result.versioned, result.reason) == (True, True, None)
    assert result.version is not None
    assert (result.version.origin, result.version.restored_from) == (
        VersionOrigin.RESTORE,
        first.id,
    )
    assert (result.version.author, result.version.recorded_at) == (AUTHOR, NOW)
    edited = rig.store.page(PROJECT, AGENT)[1]
    # The hand edit has no author (D11), and it stays restorable (AC-295.20).
    assert edited.author is None
    assert rig.store.get(PROJECT, AGENT, edited.id) is not None


SCENARIO: Final = "scenarios/demo/walk.yaml"


def test_writes_and_records_scenario_file_when_builder_saves() -> None:
    rig = _Rig({SCENARIO: b"version: 1\n"})
    unit = ItemUnit(project=PROJECT, unit_path=SCENARIO, kind=UnitKind.SCENARIO)

    result = rig.step.write(
        HUB, unit, _file("walk.yaml", b"version: 2\n"), origin=VersionOrigin.PUBLISH
    )

    assert rig.hub.skill_files[SCENARIO] == b"version: 2\n"
    assert rig.origins(SCENARIO) == [
        (VersionOrigin.EXTERNAL, file_hash(b"version: 1\n")),
        (VersionOrigin.PUBLISH, file_hash(b"version: 2\n")),
    ]
    assert (result.changed, result.versioned) == (True, True)


def test_refuses_scenario_unit_outside_scenarios_folder() -> None:
    with pytest.raises(SkillPathError):
        unit_parts("workflows/demo/walk.yaml", UnitKind.SCENARIO)
    with pytest.raises(SkillPathError):
        unit_parts("scenarios/walk.yaml", UnitKind.SCENARIO)
    assert unit_parts(SCENARIO, UnitKind.SCENARIO) == ("scenarios", "demo", "walk.yaml")


def test_writes_nothing_when_content_equal() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.seen(1)

    result = rig.step.write(HUB, _agent(), _scout(SCOUT), origin=VersionOrigin.PUBLISH)

    assert (result.changed, result.versioned, result.reason, result.version) == (
        False,
        False,
        None,
        None,
    )
    assert rig.writer.writes == []
    assert rig.origins() == [(VersionOrigin.EXTERNAL, file_hash(SCOUT))]


def test_refuses_managed_when_not_confirmed() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.seen(1)
    rig.hub.skill_files[AGENT] = EDITED
    _managed(rig, AGENT)

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    assert refused.value.code == "managed_confirmation_required"
    assert rig.hub.skill_files[AGENT] == EDITED
    assert rig.writer.writes == []
    # The disk's content is recorded before the managed check (O6), and nothing else.
    assert rig.origins() == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT)),
        (VersionOrigin.EXTERNAL, file_hash(EDITED)),
    ]

    result = rig.step.write(
        HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH, confirm_managed=True
    )

    assert result.changed
    assert rig.hub.skill_files[AGENT] == NEWER
    assert rig.origins()[-1] == (VersionOrigin.PUBLISH, file_hash(NEWER))
    assert len(rig.origins()) == len(("scout", "edited", "newer"))


def test_refuses_when_hub_read_only() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.seen(1)
    rig.hub.skill_files[AGENT] = EDITED
    rig.writer.read_only.add(HUB)

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    assert refused.value.code == "hub_read_only"
    assert rig.hub.skill_files[AGENT] == EDITED
    assert rig.origins() == [(VersionOrigin.EXTERNAL, file_hash(SCOUT))]


def test_refuses_when_no_author() -> None:
    reason = "No user.name or user.email for this hub"
    rig = _Rig({AGENT: SCOUT}, author_of=lambda _project: NoAuthor(reason))
    rig.seen(1)
    rig.hub.skill_files[AGENT] = EDITED

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    assert (refused.value.code, refused.value.reason) == ("no_author", reason)
    assert rig.hub.skill_files[AGENT] == EDITED
    assert rig.origins() == [(VersionOrigin.EXTERNAL, file_hash(SCOUT))]


def test_refuses_unreadable_when_unit_is_special() -> None:
    rig = _Rig({})
    rig.hub.skill_specials = frozenset({AGENT})

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    assert refused.value.code == "unit_unreadable"
    assert rig.writer.writes == []
    assert rig.origins() == []


def test_refuses_link_when_target_component_is_link() -> None:
    rig = _Rig({})
    rig.hub.skill_links["plugin/demo/agents"] = "../elsewhere"

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    assert refused.value.code == "link_in_path"
    assert rig.writer.writes == []
    assert rig.origins() == []


def test_records_nothing_more_when_write_fails() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.seen(1)
    rig.hub.skill_files[AGENT] = EDITED
    rig.writer.fail_on.add(AGENT)

    with pytest.raises(HubItemWriteError):
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    assert rig.hub.skill_files[AGENT] == EDITED
    # The record-first row is a true fact about the disk and stays; no publish is recorded.
    assert rig.origins() == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT)),
        (VersionOrigin.EXTERNAL, file_hash(EDITED)),
    ]


class _RollbackFailingWriter(FakeHubItemWriter):
    """A folder swap whose roll back failed too: the write raises ``rollback_failed``."""

    def write_unit(
        self, hub_path: str, unit_path: str, content: UnitContent, *, kind: UnitKind
    ) -> None:
        raise rollback_failed()


@pytest.mark.parametrize("kind", ["failed", "rollback_failed"])
def test_reads_unit_again_when_write_fails(kind: str) -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.seen(1)
    if kind == "failed":
        rig.writer.fail_on.add(AGENT)
    else:
        rig.writer = _RollbackFailingWriter({HUB: rig.hub})
        rig.step = RecordAndWrite(
            rig.store,
            reader=rig.reader,
            writer=rig.writer,
            author_of=lambda _project: AUTHOR,
            clock=lambda: NOW,
            capture=rig.capture,
        )
    reads = len(rig.reader.unit_reads)

    with pytest.raises(HubItemWriteError) as failed:
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)
    rig.seen(1)

    assert failed.value.kind == kind
    # The memo entry is dropped: the next read under the same mark reads the unit again.
    assert len(rig.reader.unit_reads) == reads + len(("write", "seen again"))


def test_unversioned_when_written_content_secret() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.seen(1)
    secret = NEWER + f"token: {SYNTHETIC_TOKEN}\n".encode()

    result = rig.step.write(HUB, _agent(), _scout(secret), origin=VersionOrigin.PUBLISH)

    assert rig.hub.skill_files[AGENT] == secret
    assert (result.changed, result.versioned, result.reason, result.version) == (
        True,
        False,
        "secret",
        None,
    )
    assert rig.origins() == [(VersionOrigin.EXTERNAL, file_hash(SCOUT))]


def test_unversioned_when_written_content_too_large() -> None:
    rig = _Rig({})
    hooks = ItemUnit(project=PROJECT, unit_path=HOOKS, kind=UnitKind.HOOK)
    large = b"{" + b" " * MAX_SKILL_FILE_BYTES + b"}"

    result = rig.step.write(HUB, hooks, _file("settings.json", large), origin=VersionOrigin.PUBLISH)

    assert rig.hub.skill_files[HOOKS] == large
    assert (result.changed, result.versioned, result.reason) == (True, False, "too_large")
    assert rig.origins(HOOKS) == []


def test_records_no_external_when_catalog_reads_after_write() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.seen(1)

    rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)
    # A catalog read under the old mark (the stat mark a coarse clock kept) reads the unit again.
    rig.seen(1)
    rig.seen(2)

    assert rig.origins() == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT)),
        (VersionOrigin.PUBLISH, file_hash(NEWER)),
    ]
    reads = ("seen", "write", "seen under the old mark", "seen under a new mark")
    assert rig.reader.unit_reads.count((HUB, AGENT)) == len(reads)


class _HeldReader(FakeHubFileReader):
    """The first read answers the content found, then waits for ``release``: a capture still
    holding what it read while a write runs."""

    def __init__(self) -> None:
        super().__init__({})
        self.entered = threading.Event()
        self.release = threading.Event()

    def read_unit(
        self, hub_path: str, unit_path: str, *, kind: UnitKind
    ) -> UnitContent | UnreadUnit:
        read = super().read_unit(hub_path, unit_path, kind=kind)
        if not self.entered.is_set():
            self.entered.set()
            self.release.wait(WAIT_SECONDS)
        return read


def test_waits_for_capture_of_unit_when_writing() -> None:
    reader = _HeldReader()
    rig = _Rig({AGENT: SCOUT}, reader=reader)
    seen = threading.Thread(target=lambda: rig.seen(1), daemon=True)
    seen.start()
    assert reader.entered.wait(WAIT_SECONDS)
    written = threading.Thread(
        target=lambda: rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH),
        daemon=True,
    )
    written.start()
    written.join(INTERLEAVE_SECONDS)

    reader.release.set()
    seen.join(WAIT_SECONDS)
    written.join(WAIT_SECONDS)

    assert not seen.is_alive()
    assert not written.is_alive()
    # The capture's older read is recorded before the write, never as an ``external`` after it.
    assert rig.origins() == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT)),
        (VersionOrigin.PUBLISH, file_hash(NEWER)),
    ]


class _RacedStore(InMemoryItemVersionStore):
    """Another process appends ``raced`` before each of this one's first ``losses`` appends."""

    def __init__(self, raced: NewItemVersion, *, losses: int) -> None:
        super().__init__()
        self.raced = raced
        self.losses = losses

    def append(self, version: NewItemVersion) -> ItemVersion:
        if self.losses > 0:
            self.losses -= 1
            last = self.last(version.project, version.unit_path)
            seq = 1 if last is None else last.seq + 1
            super().append(self.raced.model_copy(update={"seq": seq, "first": seq == 1}))
        return super().append(version)


def _raced(content: bytes) -> NewItemVersion:
    return NewItemVersion(
        project=PROJECT,
        unit_path=AGENT,
        kind=UnitKind.AGENT,
        seq=1,
        origin=VersionOrigin.EXTERNAL,
        first=True,
        recorded_at=NOW,
        content_hash=file_hash(content),
        size=len(content),
        content=content,
    )


def _raced_rig(content: bytes, *, losses: int) -> _Rig:
    rig = _Rig({AGENT: SCOUT})
    rig.store = _RacedStore(_raced(content), losses=losses)
    rig.step = RecordAndWrite(
        rig.store,
        reader=rig.reader,
        writer=rig.writer,
        author_of=lambda _project: AUTHOR,
        clock=lambda: NOW,
        capture=rig.capture,
    )
    return rig


def test_records_once_when_another_process_records_disk_first() -> None:
    rig = _raced_rig(SCOUT, losses=1)

    rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    # The disk's content lost its race to the same content: it is stored once.
    assert rig.origins() == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT)),
        (VersionOrigin.PUBLISH, file_hash(NEWER)),
    ]


def test_raises_when_race_lost_every_try() -> None:
    rig = _raced_rig(EDITED, losses=0)
    rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)
    assert isinstance(rig.store, _RacedStore)
    rig.store.losses = ATTEMPTS

    with pytest.raises(ItemVersionSequenceError):
        rig.step.write(HUB, _agent(), _scout(SCOUT), origin=VersionOrigin.PUBLISH)

    # The unit is written, but its version lost every race (the next read records it).
    assert rig.hub.skill_files[AGENT] == SCOUT
    assert rig.origins()[-1] == (VersionOrigin.EXTERNAL, file_hash(EDITED))


def test_says_written_unrecorded_when_race_lost_after_write() -> None:
    rig = _raced_rig(EDITED, losses=0)
    rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)
    assert isinstance(rig.store, _RacedStore)
    rig.store.losses = ATTEMPTS

    with pytest.raises(ItemWrittenRaceLostError) as raised:
        rig.step.write(HUB, _agent(), _scout(SCOUT), origin=VersionOrigin.PUBLISH)

    assert isinstance(raised.value, ItemVersionSequenceError)
    assert isinstance(raised.value, ItemWrittenUnrecordedError)
    assert AGENT not in str(raised.value)
    assert rig.hub.skill_files[AGENT] == SCOUT


def test_writes_nothing_when_race_lost_before_write() -> None:
    rig = _raced_rig(EDITED, losses=ATTEMPTS)

    with pytest.raises(ItemVersionSequenceError) as raised:
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    # The disk's content could not be recorded first, so the unit is left as it was.
    assert not isinstance(raised.value, ItemWrittenUnrecordedError)
    assert rig.hub.skill_files[AGENT] == SCOUT
    assert rig.writer.writes == []


class _StoreBusyError(AgentHubError):
    """Stands in for the storage adapter's busy database (a ``DatabaseAccessError``)."""


class _BusyAfterStore(InMemoryItemVersionStore):
    """Appends ``appends`` versions, then fails every append as a busy database does."""

    def __init__(self, appends: int) -> None:
        super().__init__()
        self.appends = appends

    def append(self, version: NewItemVersion) -> ItemVersion:
        if self.appends == 0:
            raise _StoreBusyError("database is locked")
        self.appends -= 1
        return super().append(version)


def test_says_written_unrecorded_when_store_fails_after_write() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.store = _BusyAfterStore(appends=1)
    rig.step = RecordAndWrite(
        rig.store,
        reader=rig.reader,
        writer=rig.writer,
        author_of=lambda _project: AUTHOR,
        clock=lambda: NOW,
        capture=rig.capture,
    )

    with pytest.raises(ItemWrittenUnrecordedError) as raised:
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    assert isinstance(raised.value.__cause__, _StoreBusyError)
    assert rig.hub.skill_files[AGENT] == NEWER
    assert rig.origins() == [(VersionOrigin.EXTERNAL, file_hash(SCOUT))]


def test_raises_store_error_when_store_fails_before_write() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.store = _BusyAfterStore(appends=0)
    rig.step = RecordAndWrite(
        rig.store,
        reader=rig.reader,
        writer=rig.writer,
        author_of=lambda _project: AUTHOR,
        clock=lambda: NOW,
        capture=rig.capture,
    )

    with pytest.raises(_StoreBusyError):
        rig.step.write(HUB, _agent(), _scout(NEWER), origin=VersionOrigin.PUBLISH)

    assert rig.hub.skill_files[AGENT] == SCOUT
    assert rig.writer.writes == []


ALPHA: Final = "plugin/demo/skills/alpha"
BETA: Final = "plugin/demo/skills/beta"
DRAFT_ID: Final = "skill-abc123"


def _skill(path: str) -> ItemUnit:
    return ItemUnit(project=PROJECT, unit_path=path, kind=UnitKind.SKILL)


def _renamed(content: UnitContent) -> Placement:
    def place(reads: UnitReads) -> Destination:
        assert isinstance(reads[ALPHA], UnitContent)
        assert reads[BETA] == UnreadUnit(kind="missing")
        return Destination(unit=_skill(BETA), content=content, removed=_skill(ALPHA))

    return place


def test_records_old_unit_then_moves_when_renamed() -> None:
    rig = _Rig({f"{ALPHA}/SKILL.md": b"# alpha\n", f"{ALPHA}/.cache/data": b"cached"})
    renamed = UnitContent(files=(UnitFile(path="SKILL.md", content=b"# beta\n"),))

    result = rig.step.publish(
        HUB,
        [_skill(ALPHA), _skill(BETA)],
        _renamed(renamed),
        confirm_managed=False,
        draft_id=DRAFT_ID,
    )

    assert {path: rig.hub.skill_files[path] for path in rig.hub.skill_files} == {
        f"{BETA}/SKILL.md": b"# beta\n",
        f"{BETA}/.cache/data": b"cached",
    }
    assert [version.origin for version in rig.store.page(PROJECT, ALPHA)] == [
        VersionOrigin.EXTERNAL
    ]
    published = rig.store.page(PROJECT, BETA)
    assert [(v.origin, v.first, v.draft_id, v.author) for v in published] == [
        (VersionOrigin.PUBLISH, True, DRAFT_ID, AUTHOR)
    ]
    assert result.version is not None
    assert result.version.draft_id == DRAFT_ID


def test_refuses_existing_script_when_other_bytes() -> None:
    hooks = "plugin/demo/hooks/hooks.json"
    script = "plugin/demo/scripts/check.sh"
    rig = _Rig({script: b"#!/bin/sh\necho other\n"})
    unit = ItemUnit(project=PROJECT, unit_path=hooks, kind=UnitKind.HOOK)

    def place(reads: UnitReads) -> Destination:
        del reads
        return Destination(
            unit=unit,
            content=_file("hooks.json", b'{"hooks": {}}\n'),
            scripts=(UnitFile(path=script, content=b"#!/bin/sh\necho mine\n"),),
        )

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.step.publish(HUB, [unit], place, confirm_managed=False, draft_id="hook-abc123")

    assert refused.value.code == "item_exists"
    assert rig.writer.writes == []
    assert rig.store.last(PROJECT, hooks) is None


SPENT_DRAFT: Final = "agent-spt001"


def _published(content: bytes) -> Placement:
    def place(reads: UnitReads) -> Destination:
        del reads
        return Destination(unit=_agent(), content=_scout(content))

    return place


def test_refuses_spent_draft_before_reading_when_publish_names_it() -> None:
    rig = _Rig({AGENT: SCOUT})
    rig.step.publish(
        HUB, [_agent()], _published(NEWER), confirm_managed=False, draft_id=SPENT_DRAFT
    )
    rig.hub.skill_files[AGENT] = EDITED
    rig.reader.unit_reads.clear()
    placed: list[UnitReads] = []

    def place(reads: UnitReads) -> Destination:
        placed.append(reads)
        return Destination(unit=_agent(), content=_scout(NEWER))

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.step.publish(HUB, [_agent()], place, confirm_managed=False, draft_id=SPENT_DRAFT)
    other = rig.step.publish(HUB, [_agent()], place, confirm_managed=False, draft_id="agent-zzz999")

    assert refused.value.code == "draft_already_published"
    assert refused.value.reason == "This draft was already published; discard it"
    assert len(placed) == 1
    assert rig.reader.unit_reads.count((HUB, AGENT)) == 1
    assert other.changed
    assert rig.origins() == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT)),
        (VersionOrigin.PUBLISH, file_hash(NEWER)),
        (VersionOrigin.EXTERNAL, file_hash(EDITED)),
        (VersionOrigin.PUBLISH, file_hash(NEWER)),
    ]


def test_refuses_second_publish_of_draft_when_first_recorded_while_it_waited() -> None:
    rig = _Rig({AGENT: SCOUT})
    entered, release = threading.Event(), threading.Event()
    placed: list[str] = []
    outcomes: dict[str, object] = {}

    def held(reads: UnitReads) -> Destination:
        del reads
        placed.append("first")
        entered.set()
        release.wait(WAIT_SECONDS)
        return Destination(unit=_agent(), content=_scout(NEWER))

    def second(reads: UnitReads) -> Destination:
        del reads
        placed.append("second")
        return Destination(unit=_agent(), content=_scout(NEWER))

    def run(name: str, place: Placement) -> None:
        try:
            outcomes[name] = rig.step.publish(
                HUB, [_agent()], place, confirm_managed=False, draft_id=SPENT_DRAFT
            )
        except ItemWriteRefusedError as refused:
            outcomes[name] = refused.code

    first_thread = threading.Thread(target=run, args=("first", held), daemon=True)
    first_thread.start()
    assert entered.wait(WAIT_SECONDS)
    second_thread = threading.Thread(target=run, args=("second", second), daemon=True)
    second_thread.start()
    second_thread.join(INTERLEAVE_SECONDS)
    # The second publish passed nothing yet: it waits for the lock the first holds.
    assert second_thread.is_alive()

    release.set()
    first_thread.join(WAIT_SECONDS)
    second_thread.join(WAIT_SECONDS)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert placed == ["first"]
    assert outcomes["second"] == "draft_already_published"
    assert rig.hub.skill_files[AGENT] == NEWER
    assert rig.origins() == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT)),
        (VersionOrigin.PUBLISH, file_hash(NEWER)),
    ]
