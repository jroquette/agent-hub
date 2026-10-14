import pytest

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
from agent_hub.core.testing.read_model_builders import a_skill_usage
from agent_hub.core.testing.skill_trees import (
    FIXTURE_PROJECT,
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


def test_marks_over_budget_when_catalog_over_sixteen_mebibytes() -> None:
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


def test_lists_too_large_when_skill_md_over_cap() -> None:
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


def test_says_not_synced_when_hub_has_no_skills() -> None:
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
