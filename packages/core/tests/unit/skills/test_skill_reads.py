from datetime import UTC, datetime

import pytest

from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_catalog import EMPTY_NOTICE
from agent_hub.core.skills.skill_reads import SkillReads
from agent_hub.core.skills.skill_sources import CATALOG_BUDGET_BYTES, MAX_SKILL_FILE_BYTES
from agent_hub.core.skills.skill_view import (
    DiagnosticCode,
    ItemKind,
    SkillFileTooLargeError,
    SkillUsage,
)
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.core.testing.item_version_fakes import InMemoryItemVersionStore
from agent_hub.core.testing.read_model_builders import a_skill_usage
from agent_hub.core.testing.skill_trees import (
    FIXTURE_PROJECT,
    Link,
    TreeEntry,
    a_skills_fixture_tree,
    fake_hub_of,
)

HUB = "/hubs/demo-hub"
ALPHA = {"kind": ItemKind.SKILL, "source": "hub-workflow", "name": "alpha"}


class FakeUsage:
    def __init__(self, usage: SkillUsage) -> None:
        self.usage = usage
        self.asked: list[str] = []

    def skill_usage(self, project: str) -> SkillUsage:
        self.asked.append(project)
        return self.usage


def _reads(
    tree: dict[str, TreeEntry] | None = None, *, usage: FakeUsage | None = None
) -> tuple[SkillReads, FakeHubFileReader, FakeHub]:
    hub = fake_hub_of(a_skills_fixture_tree() if tree is None else tree)
    reader = FakeHubFileReader({HUB: hub})
    return SkillReads(reader, usage), reader, hub


def _skill(name: str, size: int) -> bytes:
    head = f"---\nname: {name}\ndescription: Big.\n---\n".encode()
    return head + b"x" * (size - len(head))


def test_marks_over_budget_when_catalog_over_byte_bounds() -> None:
    size = 250_000
    count = CATALOG_BUDGET_BYTES // size + 3
    tree: dict[str, TreeEntry] = {
        f"plugin/extra/skills/s{index:03d}/SKILL.md": _skill(f"s{index:03d}", size)
        for index in range(count)
    }
    reads, reader, hub = _reads(tree)

    catalog = reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)

    read_bytes = sum(len(hub.skill_files[path]) for _, path in reader.skill_reads)
    assert read_bytes <= CATALOG_BUDGET_BYTES
    assert catalog.truncated
    assert catalog.notice is not None
    assert "budget" in catalog.notice
    late = reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **_extra(f"s{count - 1:03d}"))
    assert [d.code for d in late.diagnostics] == [DiagnosticCode.OVER_BUDGET]
    assert late.body is None
    assert len(catalog.items) == count


def _extra(name: str) -> dict[str, object]:
    return {"kind": ItemKind.SKILL, "source": "extra", "name": name}


def test_lists_too_large_when_skill_md_over_file_bounds() -> None:
    path = "plugin/extra/skills/huge/SKILL.md"
    reads, reader, _ = _reads({path: _skill("huge", 300 * 1024)})

    detail = reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **_extra("huge"))

    assert [d.code for d in detail.diagnostics] == [DiagnosticCode.TOO_LARGE]
    assert (detail.body, detail.raw) == (None, None)
    assert (HUB, path) not in reader.skill_reads
    assert reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB).items[0].name == "huge"


def test_reads_listing_once_when_catalog_warm() -> None:
    reads, reader, hub = _reads()
    reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)
    cold = len(reader.skill_reads)

    reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)
    reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)

    assert cold > 0
    assert len(reader.skill_reads) == cold
    assert reader.skill_listings == [HUB, HUB, HUB]
    path = "plugin/hub-workflow/skills/alpha/SKILL.md"
    hub.skill_files[path] = hub.skill_files[path] + b"\nMore.\n"
    hub.mtimes[path] = 1
    detail = reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)
    assert len(reader.skill_reads) > cold
    assert detail.raw is not None
    assert detail.raw.endswith("More.\n")


def test_keeps_one_entry_per_hub_when_files_edited() -> None:
    other = "/hubs/other-hub"
    hub, second = fake_hub_of(a_skills_fixture_tree()), fake_hub_of(a_skills_fixture_tree())
    reader = FakeHubFileReader({HUB: hub, other: second})
    reads = SkillReads(reader, memo_entries=2)
    reads.catalog(project=FIXTURE_PROJECT, hub_path=other)
    path = "plugin/hub-workflow/skills/alpha/SKILL.md"
    for edit in range(1, 5):
        hub.skill_files[path] = hub.skill_files[path] + b"\nMore.\n"
        hub.mtimes[path] = edit
        reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)
    before = len(reader.skill_reads)

    reads.catalog(project=FIXTURE_PROJECT, hub_path=other)

    assert len(reads._memo) == 2  # noqa: SLF001 - one entry per hub, whatever the edits
    assert len(reader.skill_reads) == before
    keys = list(reads._memo)  # noqa: SLF001 - the second hub's entry survived the edits
    assert keys == [(HUB, FIXTURE_PROJECT), (other, FIXTURE_PROJECT)]


def test_holds_one_entry_when_hub_edited_many_times() -> None:
    reads, _, hub = _reads()
    path = "plugin/hub-workflow/skills/alpha/SKILL.md"
    for edit in range(1, 6):
        hub.skill_files[path] = hub.skill_files[path] + b"\nMore.\n"
        hub.mtimes[path] = edit
        reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)

    assert len(reads._memo) == 1  # noqa: SLF001 - a stale fold is replaced, not kept


def test_serves_file_when_id_issued() -> None:
    tree = a_skills_fixture_tree()
    tree["plugin/hub-workflow/skills/alpha/assets/logo.png"] = b"\x89PNG\r\n\x1a\n\x00\x00"
    reads, _, _ = _reads(tree)
    detail = reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)
    ids = {bundled.path: bundled.id for bundled in detail.files}

    text = reads.file(
        project=FIXTURE_PROJECT, hub_path=HUB, file_id=ids["references/r.md"], **ALPHA
    )
    binary = reads.file(
        project=FIXTURE_PROJECT, hub_path=HUB, file_id=ids["assets/logo.png"], **ALPHA
    )

    assert (text.path, text.role, text.text, text.binary) == (
        "references/r.md",
        "references",
        "# R\n\nRead on demand.\n",
        False,
    )
    assert text.size == len(b"# R\n\nRead on demand.\n")
    assert (binary.text, binary.binary, binary.role) == (None, True, "assets")


def test_answers_not_found_when_id_unknown() -> None:
    tree = a_skills_fixture_tree()
    big = "plugin/hub-workflow/skills/alpha/references/big.md"
    tree[big] = b"x" * (MAX_SKILL_FILE_BYTES + 1)
    reads, reader, _ = _reads(tree)
    detail = reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)
    big_id = next(bundled.id for bundled in detail.files if bundled.path == "references/big.md")

    with pytest.raises(EntityNotFoundError) as unknown:
        reads.file(project=FIXTURE_PROJECT, hub_path=HUB, file_id="0" * 16, **ALPHA)
    with pytest.raises(EntityNotFoundError):
        reads.file(
            project=FIXTURE_PROJECT,
            hub_path=HUB,
            kind=ItemKind.SKILL,
            source="hub-workflow",
            name="beta",
            file_id=big_id,
        )
    with pytest.raises(SkillFileTooLargeError) as too_large:
        reads.file(project=FIXTURE_PROJECT, hub_path=HUB, file_id=big_id, **ALPHA)

    assert unknown.value.entity == "skill file"
    assert too_large.value.limit == MAX_SKILL_FILE_BYTES
    assert too_large.value.size == MAX_SKILL_FILE_BYTES + 1
    assert (HUB, big) not in reader.skill_reads


def test_says_not_synced_when_hub_empty() -> None:
    reads, _, _ = _reads({})

    catalog = reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)

    assert (catalog.items, catalog.notice) == ((), EMPTY_NOTICE)
    assert catalog.project == FIXTURE_PROJECT


@pytest.mark.parametrize(("source", "name"), [("hub-workflow", ".."), ("a.b", "alpha")])
def test_reads_nothing_when_name_unknown(source: str, name: str) -> None:
    reads, reader, _ = _reads()

    with pytest.raises(EntityNotFoundError) as refused:
        reads.detail(
            project=FIXTURE_PROJECT, hub_path=HUB, kind=ItemKind.SKILL, source=source, name=name
        )
    reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)
    warm = len(reader.skill_reads)
    with pytest.raises(EntityNotFoundError) as unknown:
        reads.detail(
            project=FIXTURE_PROJECT,
            hub_path=HUB,
            kind=ItemKind.AGENT,
            source="hub-workflow",
            name="alpha",
        )

    assert refused.value.entity == "skill"
    assert unknown.value.entity_id == "agent/hub-workflow/alpha"
    assert reader.skill_listings == [HUB, HUB]
    assert len(reader.skill_reads) == warm


@pytest.mark.parametrize(
    ("kind", "source", "name"),
    [
        pytest.param(ItemKind.SKILL, "hub-workflow", "missing", id="skill-name"),
        pytest.param(ItemKind.SKILL, "nowhere", "alpha", id="skill-source"),
        pytest.param(ItemKind.AGENT, "hub-workflow", "alpha", id="agent-kind"),
        pytest.param(ItemKind.HOOK, "nowhere", "nowhere-stop-1", id="hook-source"),
        pytest.param(ItemKind.HOOK, "settings", "other-stop-1", id="hook-name"),
    ],
)
def test_refuses_unknown_item_without_reading_when_catalog_cold(
    kind: ItemKind, source: str, name: str
) -> None:
    reads, reader, _ = _reads()

    with pytest.raises(EntityNotFoundError) as unknown:
        reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, kind=kind, source=source, name=name)
    with pytest.raises(EntityNotFoundError):
        reads.file(
            project=FIXTURE_PROJECT,
            hub_path=HUB,
            kind=kind,
            source=source,
            name=name,
            file_id="0" * 16,
        )

    assert unknown.value.entity_id == f"{kind.value}/{source}/{name}"
    assert reader.skill_reads == []
    assert reader.skill_listings == [HUB, HUB]


def test_reads_item_when_listed_and_catalog_cold() -> None:
    reads, reader, _ = _reads()

    detail = reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)
    hook = reads.detail(
        project=FIXTURE_PROJECT,
        hub_path=HUB,
        kind=ItemKind.HOOK,
        source="settings",
        name="settings-pretooluse-1",
    )

    assert detail.id == "skill/hub-workflow/alpha"
    assert hook.id == "hook/settings/settings-pretooluse-1"
    assert reader.skill_reads != []


def test_refuses_ids_when_they_end_with_newline() -> None:
    reads, reader, _ = _reads()
    detail = reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)
    issued = detail.files[0].id
    newline = {**ALPHA, "name": "alpha\n"}

    with pytest.raises(EntityNotFoundError):
        reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **newline)
    with pytest.raises(EntityNotFoundError):
        reads.file(project=FIXTURE_PROJECT, hub_path=HUB, file_id=f"{issued}\n", **ALPHA)
    with pytest.raises(EntityNotFoundError):
        reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **{**ALPHA, "source": "hub-workflow\n"})

    assert reader.skill_listings == [HUB]


def test_joins_usage_when_source_given() -> None:
    usage = FakeUsage(a_skill_usage())
    reads, _, _ = _reads(usage=usage)

    catalog = reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)
    detail = reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)

    counts = {item.id: None if item.usage is None else item.usage.count for item in catalog.items}
    assert counts["skill/hub-workflow/alpha"] == 3
    assert counts["agent/hub-workflow/evaluator"] == 1
    assert counts["skill/hub-workflow/beta"] == 0
    assert counts["hook/settings/settings-pretooluse-1"] is None
    assert detail.usage is not None
    assert (detail.usage.user_count, detail.usage.model_count) == (2, 1)
    assert usage.asked == [FIXTURE_PROJECT, FIXTURE_PROJECT]


def test_counts_zero_when_no_usage_source() -> None:
    reads, _, _ = _reads()

    catalog = reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)

    alpha = next(item for item in catalog.items if item.name == "alpha")
    assert alpha.usage is not None
    assert alpha.usage.count == 0


# Every unit of the AC-164.1 tree: the ``.claude/skills/alpha`` link is versioned at its
# target, and the ``settings.json`` hooks share one file.
FIXTURE_UNITS = {
    "plugin/hub-workflow/skills/alpha",
    "plugin/hub-workflow/skills/beta",
    "plugin/demo/skills/gamma",
    "plugin/extra/skills/delta",
    ".claude/skills/local-one",
    "plugin/hub-workflow/agents/evaluator.md",
    "plugin/demo/agents/scout.md",
    ".claude/agents/local-agent.md",
    "plugin/hub-workflow/hooks/hooks.json",
    ".claude/settings.json",
}


def _capturing(
    extra: dict[str, TreeEntry] | None = None,
) -> tuple[SkillReads, FakeHubFileReader, FakeHub, InMemoryItemVersionStore]:
    hub = fake_hub_of(a_skills_fixture_tree() | (extra or {}))
    reader = FakeHubFileReader({HUB: hub})
    store = InMemoryItemVersionStore()
    capture = CaptureItemVersions(store, reader, lambda: datetime(2026, 10, 17, tzinfo=UTC))
    return SkillReads(reader, capture=capture), reader, hub, store


def test_captures_units_when_catalog_read() -> None:
    reads, reader, _, store = _capturing()

    reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)
    reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)

    read_paths = [path for _, path in reader.unit_reads]
    assert sorted(read_paths) == sorted(FIXTURE_UNITS)
    for path in FIXTURE_UNITS:
        last = store.last(FIXTURE_PROJECT, path)
        assert last is not None, path
        assert (last.seq, last.first) == (1, True)


def test_captures_one_unit_when_detail_read() -> None:
    reads, reader, hub, store = _capturing()
    reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)
    alpha = "plugin/hub-workflow/skills/alpha"
    path = f"{alpha}/references/r.md"
    hub.skill_files[path] = hub.skill_files[path] + b"More.\n"
    hub.mtimes[path] = 1

    reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **ALPHA)

    assert [path for _, path in reader.unit_reads] == [alpha, alpha]
    assert [version.seq for version in store.page(FIXTURE_PROJECT, alpha)] == [2, 1]


def test_names_unit_when_item_listed() -> None:
    reads, reader, _, _ = _capturing({".claude/skills/out": Link("/elsewhere/out")})

    alpha = reads.marked_unit(FIXTURE_PROJECT, HUB, **ALPHA)
    hook = reads.marked_unit(
        FIXTURE_PROJECT, HUB, kind=ItemKind.HOOK, source="settings", name="settings-pretooluse-1"
    )
    linked = reads.marked_unit(
        FIXTURE_PROJECT, HUB, kind=ItemKind.SKILL, source="claude", name="out"
    )

    assert alpha is not None
    assert alpha.unit == ItemUnit(
        project=FIXTURE_PROJECT, unit_path="plugin/hub-workflow/skills/alpha", kind=UnitKind.SKILL
    )
    assert hook is not None
    assert hook.unit.unit_path == ".claude/settings.json"
    assert linked is None
    assert reader.unit_reads == []
    with pytest.raises(EntityNotFoundError):
        reads.marked_unit(FIXTURE_PROJECT, HUB, kind=ItemKind.SKILL, source="claude", name="alpha")


def test_marks_unit_as_detail_captures_when_hooks_share_file() -> None:
    hub = fake_hub_of(a_skills_fixture_tree())
    reader = FakeHubFileReader({HUB: hub})
    capture = CaptureItemVersions(
        InMemoryItemVersionStore(), reader, lambda: datetime(2026, 10, 18, tzinfo=UTC)
    )
    reads = SkillReads(reader, capture=capture)
    hook = {"kind": ItemKind.HOOK, "source": "settings", "name": "settings-pretooluse-1"}
    catalog = reads.catalog(project=FIXTURE_PROJECT, hub_path=HUB)
    reads.detail(project=FIXTURE_PROJECT, hub_path=HUB, **hook)
    read_before = len(reader.unit_reads)

    marked = reads.marked_unit(FIXTURE_PROJECT, HUB, **hook)

    assert marked is not None
    in_file = [item for item in catalog.items if item.source_path == ".claude/settings.json"]
    assert (marked.hub_path, marked.unit.unit_path, marked.shared_by) == (
        HUB,
        ".claude/settings.json",
        len(in_file),
    )
    assert len(in_file) > 1
    # The same mark as the detail's: the memo answers without reading the unit again.
    capture.capture(FIXTURE_PROJECT, HUB, [(marked.unit, marked.mark)])
    assert len(reader.unit_reads) == read_before
