import json
import random
from collections.abc import Mapping

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.doctor.snapshot import LockAbsent
from agent_hub.core.skills.skill_catalog import build_catalog, catalog_reads
from agent_hub.core.skills.skill_sources import CatalogInputs, SkillSources
from agent_hub.core.skills.skill_view import (
    CatalogItem,
    DiagnosticCode,
    ItemKind,
    Mode,
    Origin,
    SkillCatalog,
)
from agent_hub.core.testing.hub_fakes import FakeHubFileReader
from agent_hub.core.testing.skill_trees import (
    FIXTURE_PROJECT,
    Fifo,
    Link,
    TreeEntry,
    a_skills_fixture_tree,
    fake_hub_of,
)

HUB = "/hubs/demo-hub"


def _inputs(tree: Mapping[str, TreeEntry], **fields: object) -> CatalogInputs:
    hub = fake_hub_of(tree)
    for name, value in fields.items():
        setattr(hub, name, value)
    reader = FakeHubFileReader({HUB: hub})
    sources = reader.skill_sources(HUB)
    texts = {
        path: reader.read_skill_file(HUB, path, max_bytes=1_048_576)
        for path in catalog_reads(sources)
    }
    return CatalogInputs(
        project=FIXTURE_PROJECT,
        project_plugin=FIXTURE_PROJECT,
        sources=sources,
        texts=texts,
        lock=reader.read_lock(HUB),
    )


def _catalog(tree: Mapping[str, TreeEntry], **fields: object) -> SkillCatalog:
    return build_catalog(_inputs(tree, **fields)).catalog


def _item(catalog: SkillCatalog, item: str) -> CatalogItem:
    found = [entry for entry in catalog.items if entry.id == item]
    assert len(found) == 1, item
    return found[0]


def test_holds_exact_items_when_fixture_tree_folded() -> None:
    catalog = _catalog(a_skills_fixture_tree())

    skills = [item.name for item in catalog.items if item.kind is ItemKind.SKILL]
    agents = [item.name for item in catalog.items if item.kind is ItemKind.AGENT]
    hooks = [(item.source, item.name) for item in catalog.items if item.kind is ItemKind.HOOK]
    assert sorted(skills) == ["alpha", "beta", "delta", "gamma", "local-one"]
    assert sorted(agents) == ["evaluator", "local-agent", "scout"]
    assert sorted(hooks) == [
        ("hub-workflow", "hub-workflow-stop-1"),
        ("settings", "settings-pretooluse-1"),
        ("settings", "settings-sessionstart-1"),
    ]
    alpha = _item(catalog, "skill/hub-workflow/alpha")
    assert alpha.linked_from == (".claude/skills/alpha",)
    assert alpha.source_path == "plugin/hub-workflow/skills/alpha/SKILL.md"
    assert alpha.invocation == "/alpha <issue id>"
    assert alpha.description == "Checks the alpha flow before a release."
    origins = {item.id: item.origin for item in catalog.items}
    assert origins["skill/hub-workflow/alpha"] is Origin.MANAGED
    assert origins["agent/hub-workflow/evaluator"] is Origin.MANAGED
    assert origins["skill/demo/gamma"] is Origin.PROJECT_OWNED
    assert origins["skill/extra/delta"] is Origin.PROJECT_OWNED
    assert origins["skill/claude/local-one"] is Origin.LOCAL
    assert origins["agent/claude/local-agent"] is Origin.LOCAL
    assert _item(catalog, "agent/hub-workflow/evaluator").invocation is None
    assert [item.kind for item in catalog.items][:5] == [ItemKind.SKILL] * 5
    assert catalog.project == FIXTURE_PROJECT
    assert (catalog.truncated, catalog.notice) == (False, None)


def test_folds_hook_origins_when_settings_differ() -> None:
    tree = a_skills_fixture_tree()
    tree[".claude/settings.project.json"] = json.dumps(
        {
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": "make brain-brief"}]}],
                "Stop": [{"hooks": [{"type": "command", "command": "make lint"}]}],
            }
        }
    ).encode()

    catalog = _catalog(tree)

    merged = _item(catalog, "hook/settings/settings-sessionstart-1")
    managed = _item(catalog, "hook/settings/settings-pretooluse-1")
    missing = _item(catalog, "hook/settings-project/settings-project-stop-1")
    plugin = _item(catalog, "hook/hub-workflow/hub-workflow-stop-1")
    assert (merged.origin, merged.state, merged.active) == (Origin.PROJECT_OWNED, "synced", True)
    assert (managed.origin, managed.state) == (Origin.MANAGED, "synced")
    assert (missing.origin, missing.state) == (Origin.PROJECT_OWNED, "not synced")
    assert (plugin.origin, plugin.active) == (Origin.MANAGED, False)
    assert plugin.source_path == "plugin/hub-workflow/hooks/hooks.json"
    assert (plugin.mode, plugin.invocation, plugin.usage) == (None, None, None)
    detail = build_catalog(_inputs(tree)).details[plugin.id]
    assert detail.hook is not None
    assert detail.hook.event == "Stop"


def _flags(*lines: str) -> bytes:
    return ("---\nname: flagged\ndescription: Flags.\n" + "".join(lines) + "---\n# F\n").encode()


@pytest.mark.parametrize(
    ("lines", "mode"),
    [
        ((), Mode.BOTH),
        (("disable-model-invocation: true\n",), Mode.USER_ONLY),
        (("user-invocable: false\n",), Mode.MODEL_ONLY),
        (("disable-model-invocation: true\n", "user-invocable: false\n"), Mode.NEITHER),
        (("disable-model-invocation: false\n", "user-invocable: true\n"), Mode.BOTH),
    ],
)
def test_derives_mode_when_flags_combined(lines: tuple[str, ...], mode: Mode) -> None:
    catalog = _catalog({"plugin/demo/skills/flagged/SKILL.md": _flags(*lines)})

    assert _item(catalog, "skill/demo/flagged").mode is mode


def test_marks_links_when_targets_escape() -> None:
    tree: dict[str, TreeEntry] = {
        ".claude/skills/out": Link("../../../outside"),
        ".claude/skills/abs": Link("/etc"),
        ".claude/skills/blank": Link(""),
        "plugin/extra/skills/linked/SKILL.md": Link("../../../../../etc/passwd"),
        "plugin/extra/skills/piped/SKILL.md": Fifo(),
    }

    folded = build_catalog(_inputs(tree))

    for item in ("skill/claude/out", "skill/claude/abs", "skill/claude/blank"):
        detail = folded.details[item]
        assert [d.code for d in detail.diagnostics] == [DiagnosticCode.LINK_OUTSIDE_HUB], item
        assert (detail.body, detail.raw) == (None, None)
    linked = folded.details["skill/extra/linked"]
    piped = folded.details["skill/extra/piped"]
    assert [d.code for d in linked.diagnostics] == [DiagnosticCode.LINK_OUTSIDE_HUB]
    assert [d.code for d in piped.diagnostics] == [DiagnosticCode.NOT_REGULAR]
    messages = " ".join(d.message for detail in folded.details.values() for d in detail.diagnostics)
    assert "/etc" not in messages
    assert 'outside"' not in messages
    assert "passwd" not in messages


def test_lists_item_with_diagnostic_when_file_unread() -> None:
    tree: dict[str, TreeEntry] = {
        "plugin/extra/skills/big/SKILL.md": b"---\nname: big\n---\n" + b"x" * 300_000,
        "plugin/extra/skills/binary/SKILL.md": b"---\nname: binary\n---\n\xff\xfe",
        "plugin/extra/agents/nul.md": b"---\nname: nul\n---\n\x00",
    }
    inputs = _inputs(tree)
    texts = dict(inputs.texts)
    del texts["plugin/extra/skills/big/SKILL.md"]
    folded = build_catalog(
        CatalogInputs(
            project=inputs.project,
            project_plugin=inputs.project_plugin,
            sources=inputs.sources,
            texts=texts,
            lock=inputs.lock,
        )
    )

    codes = {item: [d.code for d in detail.diagnostics] for item, detail in folded.details.items()}
    assert codes["skill/extra/big"] == [DiagnosticCode.TOO_LARGE]
    assert codes["skill/extra/binary"] == [DiagnosticCode.NOT_TEXT]
    assert codes["agent/extra/nul"] == [DiagnosticCode.NOT_TEXT]
    assert all(folded.details[item].body is None for item in codes)
    assert _item(folded.catalog, "skill/extra/big").diagnostics_count == 1


def test_marks_over_budget_when_inputs_say_so() -> None:
    inputs = _inputs({"plugin/extra/skills/late/SKILL.md": b"---\nname: late\n---\n"})
    folded = build_catalog(
        CatalogInputs(
            project=inputs.project,
            project_plugin=inputs.project_plugin,
            sources=inputs.sources,
            texts={},
            lock=inputs.lock,
            over_budget=frozenset({"plugin/extra/skills/late/SKILL.md"}),
        )
    )

    detail = folded.details["skill/extra/late"]
    assert [d.code for d in detail.diagnostics] == [DiagnosticCode.OVER_BUDGET]
    assert folded.catalog.truncated
    assert folded.catalog.notice is not None
    assert "budget" in folded.catalog.notice


def test_keeps_folder_origins_when_lock_unread() -> None:
    catalog = _catalog(a_skills_fixture_tree(), lock=LockAbsent())

    assert _item(catalog, "skill/hub-workflow/alpha").origin is Origin.MANAGED
    assert _item(catalog, "skill/demo/gamma").origin is Origin.PROJECT_OWNED
    assert _item(catalog, "skill/claude/local-one").origin is Origin.LOCAL
    assert catalog.notice == "hub.lock not read: origins from folder names"


def test_skips_plugin_folder_when_name_reserved() -> None:
    catalog = _catalog(
        {
            "plugin/claude/skills/one/SKILL.md": b"---\nname: one\n---\n",
            "plugin/demo/skills/two/SKILL.md": b"---\nname: two\n---\n",
        }
    )

    assert [item.id for item in catalog.items] == ["skill/demo/two"]
    assert catalog.notice is not None
    assert "plugin/claude" in catalog.notice


def test_says_not_synced_when_tree_empty() -> None:
    catalog = _catalog({})

    assert catalog.items == ()
    assert catalog.notice == "No skills found in this hub; it may not be synced yet."


def test_marks_truncated_when_listing_stopped() -> None:
    inputs = _inputs({"plugin/demo/skills/one/SKILL.md": b"---\nname: one\n---\n"})
    sources = SkillSources(files=inputs.sources.files, truncated=True, skipped=3)
    folded = build_catalog(
        CatalogInputs(
            project=inputs.project,
            project_plugin=inputs.project_plugin,
            sources=sources,
            texts=inputs.texts,
            lock=inputs.lock,
        )
    )

    assert folded.catalog.truncated
    assert folded.catalog.notice is not None


@settings(max_examples=25, deadline=None)
@given(st.randoms(use_true_random=False))
def test_gives_same_catalog_when_sources_shuffled_property(rng: random.Random) -> None:
    inputs = _inputs(a_skills_fixture_tree())
    files = list(inputs.sources.files)
    rng.shuffle(files)
    texts = list(inputs.texts.items())
    rng.shuffle(texts)
    shuffled = CatalogInputs(
        project=inputs.project,
        project_plugin=inputs.project_plugin,
        sources=SkillSources(files=tuple(files)),
        texts=dict(texts),
        lock=inputs.lock,
    )

    assert build_catalog(shuffled) == build_catalog(inputs)
