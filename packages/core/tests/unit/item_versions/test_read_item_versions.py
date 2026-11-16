"""The history reads (AGH-295, S7, S8, S10, AC-295.8, .10, .27, .28): a list captures its one unit
first, so its ``state`` is the disk's now; a version is answered only within its own unit; an item
without a unit has no history."""

from datetime import UTC, datetime
from typing import Final

import pytest

from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry
from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions, UnitState
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.item_version_ports import MarkedUnit, ToolkitRef, WorkflowRef
from agent_hub.core.item_versions.read_item_versions import ReadItemVersions
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_view import ItemKind
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.core.testing.item_version_fakes import InMemoryItemVersionStore
from agent_hub.core.testing.skill_trees import FIXTURE_PLATFORM_VERSION

HUB: Final = "/hubs/demo-hub"
PROJECT: Final = "demo"
NOW: Final = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
SCOUT: Final = "plugin/demo/agents/scout.md"
SCRIBE: Final = "plugin/demo/agents/scribe.md"
ALPHA: Final = "plugin/demo/skills/alpha"
ALPHA_MD: Final = b"---\nname: alpha\ndescription: Alpha.\n---\n# Alpha\n"
REVIEW: Final = "workflows/demo/review.yaml"
SCOUT_MD: Final = b"---\nname: scout\ndescription: Scouts.\n---\nScout the repo.\n"
SCRIBE_MD: Final = b"---\nname: scribe\ndescription: Writes.\n---\nWrite it down.\n"
REVIEW_YAML: Final = b"version: 1\nname: review\nrevision: 1\nnodes: []\n"
# A synthetic GitHub token, built from fragments so no format-valid secret is one literal.
SYNTHETIC_TOKEN: Final = "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


class _Units:
    """Both unit ports over fixed answers: a known item without a unit maps to None."""

    def __init__(self, units: dict[str, ItemUnit | None]) -> None:
        self._units = units
        self.marks: dict[str, object] = {}

    def _marked(self, key: str) -> MarkedUnit | None:
        if key not in self._units:
            raise EntityNotFoundError(entity="skill", entity_id=key)
        unit = self._units[key]
        if unit is None:
            return None
        return MarkedUnit(hub_path=HUB, unit=unit, mark=self.marks.get(key, 1), shared_by=1)

    def marked_skill_unit(
        self, project: str, *, kind: ItemKind, source: str, name: str
    ) -> MarkedUnit | None:
        return self._marked(f"{project}:{kind.value}/{source}/{name}")

    def marked_workflow_unit(self, project: str, name: str) -> MarkedUnit | None:
        return self._marked(f"{project}:{name}")


def _unit(path: str, kind: UnitKind) -> ItemUnit:
    return ItemUnit(project=PROJECT, unit_path=path, kind=kind)


def _rig(files: dict[str, bytes]) -> tuple[ReadItemVersions, FakeHub, _Units]:
    hub = FakeHub(skill_files=files)
    reader = FakeHubFileReader({HUB: hub})
    store = InMemoryItemVersionStore()
    capture = CaptureItemVersions(store, reader, lambda: NOW)
    units = _Units(
        {
            f"{PROJECT}:agent/demo/scout": _unit(SCOUT, UnitKind.AGENT),
            f"{PROJECT}:agent/demo/scribe": _unit(SCRIBE, UnitKind.AGENT),
            f"{PROJECT}:skill/claude/out": None,
            f"{PROJECT}:skill/demo/alpha": _unit(ALPHA, UnitKind.SKILL),
            f"{PROJECT}:review": _unit(REVIEW, UnitKind.WORKFLOW),
        }
    )
    reads = ReadItemVersions(
        store, reader=reader, toolkit_units=units, workflow_units=units, capture=capture
    )
    return reads, hub, units


SCOUT_REF: Final = ToolkitRef(project=PROJECT, kind=ItemKind.AGENT, source="demo", name="scout")
SCRIBE_REF: Final = ToolkitRef(project=PROJECT, kind=ItemKind.AGENT, source="demo", name="scribe")


def test_lists_state_secret_when_disk_matches() -> None:
    reads, hub, units = _rig({SCOUT: SCOUT_MD})
    first = reads.list(SCOUT_REF, limit=50, cursor=None)
    hub.skill_files[SCOUT] = SCOUT_MD + f"Push with {SYNTHETIC_TOKEN}.\n".encode()
    units.marks[f"{PROJECT}:agent/demo/scout"] = 2

    page = reads.list(SCOUT_REF, limit=50, cursor=None)

    assert (first.state, len(first.items)) == (UnitState.OK, 1)
    # The earlier version stays listed; the secret content is not stored.
    assert page.state is UnitState.SECRET
    assert [item.id for item in page.items] == [first.items[0].id]
    assert (page.unit_path, page.unit_kind, page.managed, page.shared_by) == (
        SCOUT,
        UnitKind.AGENT,
        False,
        1,
    )
    content = reads.get(SCOUT_REF, first.items[0].id)
    assert [(file.path, file.text) for file in content.files] == [("scout.md", SCOUT_MD.decode())]


def test_answers_not_found_when_version_of_other_unit() -> None:
    reads, _, _ = _rig({SCOUT: SCOUT_MD, SCRIBE: SCRIBE_MD, REVIEW: REVIEW_YAML})
    scout = reads.list(SCOUT_REF, limit=50, cursor=None).items[0]
    reads.list(SCRIBE_REF, limit=50, cursor=None)
    review = reads.list(WorkflowRef(project=PROJECT, name="review"), limit=50, cursor=None)

    assert review.items[0].first
    with pytest.raises(EntityNotFoundError):
        reads.get(SCRIBE_REF, scout.id)
    with pytest.raises(EntityNotFoundError):
        reads.get(WorkflowRef(project=PROJECT, name="review"), scout.id)
    assert reads.get(SCOUT_REF, scout.id).id == scout.id


def test_no_history_when_item_has_no_unit() -> None:
    reads, _, _ = _rig({SCOUT: SCOUT_MD})
    out = ToolkitRef(project=PROJECT, kind=ItemKind.SKILL, source="claude", name="out")

    with pytest.raises(EntityNotFoundError) as listed:
        reads.list(out, limit=50, cursor=None)
    with pytest.raises(EntityNotFoundError):
        reads.get(out, "0199f0a0-0000-7000-8000-000000000000")
    with pytest.raises(EntityNotFoundError) as unknown:
        reads.list(
            ToolkitRef(project=PROJECT, kind=ItemKind.AGENT, source="demo", name="nope"),
            limit=50,
            cursor=None,
        )

    assert listed.value.entity == "item history"
    assert unknown.value.entity == "skill"


def test_lists_managed_when_lock_lists_skill_md() -> None:
    reads, hub, _ = _rig({f"{ALPHA}/SKILL.md": ALPHA_MD, SCOUT: SCOUT_MD})
    entry = ManagedFileEntry(ownership="managed", sha256="ab" * 32, executable=False)
    hub.lock = HubLock(
        lock_version=1,
        platform_version=FIXTURE_PLATFORM_VERSION,
        schema_version=1,
        modules=(),
        files={f"{ALPHA}/SKILL.md": entry},
    )
    alpha = ToolkitRef(project=PROJECT, kind=ItemKind.SKILL, source="demo", name="alpha")

    page = reads.list(alpha, limit=50, cursor=None)

    # A skill's main path is its SKILL.md (A4); the agent the lock does not list is not managed.
    assert (page.managed, page.unit_kind, len(page.items)) == (True, UnitKind.SKILL, 1)
    assert not reads.list(SCOUT_REF, limit=50, cursor=None).managed
