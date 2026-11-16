"""Restore (AGH-295, D4, D12, D22, S10, AC-295.19, .20): the chosen version of the item's own unit
is written back and a ``restore`` version naming it is appended, the earlier versions unchanged;
a unit whose disk content is a secret match is never restored over."""

from datetime import UTC, datetime
from typing import Final

import pytest

from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.item_versions.hub_item_writer import ItemWriteRefusedError
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind, VersionAuthor, VersionOrigin
from agent_hub.core.item_versions.item_version_ports import MarkedUnit, ToolkitRef, WorkflowRef
from agent_hub.core.item_versions.record_and_write import RecordAndWrite
from agent_hub.core.item_versions.restore_item_version import RestoreItemVersion
from agent_hub.core.item_versions.unit_hash import file_hash
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_view import ItemKind
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.core.testing.item_version_fakes import FakeHubItemWriter, InMemoryItemVersionStore

HUB: Final = "/hubs/demo-hub"
PROJECT: Final = "demo"
NOW: Final = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
SCOUT: Final = "plugin/demo/agents/scout.md"
SCRIBE: Final = "plugin/demo/agents/scribe.md"
REVIEW: Final = "workflows/demo/review.yaml"
ALPHA: Final = "plugin/demo/skills/alpha"
ALPHA_MD: Final = b"---\nname: alpha\ndescription: Alpha.\n---\n# Alpha\n"
AUTHOR: Final = VersionAuthor(name="Dev One", email="dev@example.com")
SCOUT_REF: Final = ToolkitRef(project=PROJECT, kind=ItemKind.AGENT, source="demo", name="scout")
REVIEW_REF: Final = WorkflowRef(project=PROJECT, name="review")
# A synthetic GitHub token, built from fragments so no format-valid secret is one literal.
SYNTHETIC_TOKEN: Final = "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def _agent(path: str) -> ItemUnit:
    return ItemUnit(project=PROJECT, unit_path=path, kind=UnitKind.AGENT)


def _skill() -> ItemUnit:
    return ItemUnit(project=PROJECT, unit_path=ALPHA, kind=UnitKind.SKILL)


def _text(version: int) -> bytes:
    return f"---\nname: scout\ndescription: Scouts.\n---\nVersion {version}.\n".encode()


class _Units:
    """Both unit ports over fixed units, each under a mark the test moves."""

    def __init__(self) -> None:
        self.units = {
            "agent/demo/scout": _agent(SCOUT),
            "scribe": _agent(SCRIBE),
            "skill/demo/alpha": _skill(),
        }
        self.mark = 0

    def marked_skill_unit(
        self, project: str, *, kind: ItemKind, source: str, name: str
    ) -> MarkedUnit | None:
        return self._marked(f"{kind.value}/{source}/{name}")

    def marked_workflow_unit(self, project: str, name: str) -> MarkedUnit | None:
        if name == "review":
            unit = ItemUnit(project=PROJECT, unit_path=REVIEW, kind=UnitKind.WORKFLOW)
            return MarkedUnit(hub_path=HUB, unit=unit, mark=self.mark, shared_by=1)
        return self._marked(name)

    def _marked(self, key: str) -> MarkedUnit | None:
        if key not in self.units:
            raise EntityNotFoundError(entity="skill", entity_id=key)
        return MarkedUnit(hub_path=HUB, unit=self.units[key], mark=self.mark, shared_by=1)


class _Rig:
    def __init__(self) -> None:
        self.hub = FakeHub()
        reader = FakeHubFileReader({HUB: self.hub})
        self.store = InMemoryItemVersionStore()
        self.capture = CaptureItemVersions(self.store, reader, lambda: NOW)
        self.units = _Units()
        step = RecordAndWrite(
            self.store,
            reader=reader,
            writer=FakeHubItemWriter({HUB: self.hub}),
            author_of=lambda _project: AUTHOR,
            clock=lambda: NOW,
            capture=self.capture,
        )
        self.restore = RestoreItemVersion(
            self.store, toolkit_units=self.units, workflow_units=self.units, step=step
        )

    def put(self, path: str, content: bytes) -> None:
        """Change the file and read it as a catalog read would."""
        self.hub.skill_files[path] = content
        self.units.mark += 1
        self.capture.capture(PROJECT, HUB, [(_agent(path), self.units.mark)])


def test_appends_restore_when_earlier_restored() -> None:
    rig = _Rig()
    for version in (1, 2, 3):
        rig.put(SCOUT, _text(version))
    before = rig.store.page(PROJECT, SCOUT)
    first = before[-1]

    result = rig.restore.restore(SCOUT_REF, first.id, confirm_managed=False)

    assert rig.hub.skill_files[SCOUT] == _text(1)
    after = rig.store.page(PROJECT, SCOUT)
    assert after[1:] == before
    restored = after[0]
    assert (restored.seq, restored.origin, restored.restored_from) == (
        len(("v1", "v2", "v3", "restore")),
        VersionOrigin.RESTORE,
        first.id,
    )
    assert (restored.author, restored.content_hash) == (AUTHOR, file_hash(_text(1)))
    assert result.version is not None
    assert result.version.id == restored.id


def test_refuses_secret_on_disk_when_restoring() -> None:
    rig = _Rig()
    rig.put(SCOUT, _text(1))
    first = rig.store.page(PROJECT, SCOUT)[0]
    secret = _text(2) + f"token: {SYNTHETIC_TOKEN}\n".encode()
    rig.put(SCOUT, secret)

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.restore.restore(SCOUT_REF, first.id, confirm_managed=False)

    assert refused.value.code == "secret_unversioned"
    assert rig.hub.skill_files[SCOUT] == secret
    assert [version.id for version in rig.store.page(PROJECT, SCOUT)] == [first.id]


def test_answers_not_found_when_version_of_other_unit() -> None:
    rig = _Rig()
    rig.put(SCOUT, _text(1))
    rig.put(SCRIBE, _text(2))
    scribe = rig.store.page(PROJECT, SCRIBE)[0]

    with pytest.raises(EntityNotFoundError) as missing:
        rig.restore.restore(SCOUT_REF, scribe.id, confirm_managed=False)

    assert missing.value.entity == "item version"
    assert rig.hub.skill_files[SCOUT] == _text(1)


def test_restores_workflow_file_when_hub_workflow_restored() -> None:
    rig = _Rig()
    workflow = ItemUnit(project=PROJECT, unit_path=REVIEW, kind=UnitKind.WORKFLOW)
    for revision in (1, 2):
        rig.hub.skill_files[REVIEW] = f"version: 1\nname: review\nrevision: {revision}\n".encode()
        rig.units.mark += 1
        rig.capture.capture(PROJECT, HUB, [(workflow, rig.units.mark)])
    first = rig.store.page(PROJECT, REVIEW)[-1]

    result = rig.restore.restore(REVIEW_REF, first.id, confirm_managed=False)

    assert rig.hub.skill_files[REVIEW] == b"version: 1\nname: review\nrevision: 1\n"
    assert result.changed


def test_restores_folder_when_skill_version_restored() -> None:
    rig = _Rig()
    rig.hub.skill_files.update(
        {
            f"{ALPHA}/SKILL.md": ALPHA_MD,
            f"{ALPHA}/references/r.md": b"# R\n",
            f"{ALPHA}/scripts/s.sh": b"echo s\n",
        }
    )
    rig.hub.executable = frozenset({f"{ALPHA}/scripts/s.sh"})
    rig.capture.capture(PROJECT, HUB, [(_skill(), 1)])
    first = rig.store.page(PROJECT, ALPHA)[0]
    rig.hub.skill_files[f"{ALPHA}/references/r.md"] = b"# R changed\n"
    rig.hub.skill_files[f"{ALPHA}/assets/new.png"] = b"\x89PNG"
    rig.hub.executable = frozenset()
    skill = ToolkitRef(project=PROJECT, kind=ItemKind.SKILL, source="demo", name="alpha")

    result = rig.restore.restore(skill, first.id, confirm_managed=False)

    assert {
        path: content for path, content in rig.hub.skill_files.items() if path.startswith(ALPHA)
    } == {
        f"{ALPHA}/SKILL.md": ALPHA_MD,
        f"{ALPHA}/references/r.md": b"# R\n",
        f"{ALPHA}/scripts/s.sh": b"echo s\n",
    }
    assert rig.hub.executable == {f"{ALPHA}/scripts/s.sh"}
    assert result.version is not None
    assert (result.version.origin, result.version.content_hash) == (
        VersionOrigin.RESTORE,
        first.content_hash,
    )
    # The changed folder was recorded first, between the baseline and the restore.
    assert [version.origin for version in rig.store.page(PROJECT, ALPHA)] == [
        VersionOrigin.RESTORE,
        VersionOrigin.EXTERNAL,
        VersionOrigin.EXTERNAL,
    ]
