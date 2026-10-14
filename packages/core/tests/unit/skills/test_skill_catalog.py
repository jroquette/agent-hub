import json
import random
from collections.abc import Mapping

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.doctor.snapshot import LockAbsent
from agent_hub.core.skills.skill_catalog import build_catalog, catalog_reads
from agent_hub.core.skills.skill_sources import (
    CatalogInputs,
    FoldedCatalog,
    SkillSources,
    SourceFile,
    file_id,
)
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


def test_skips_names_when_they_end_with_newline() -> None:
    # The adapters refuse such names when listing; the fold refuses them on its own too.
    inputs = _inputs({"plugin/demo/skills/two/SKILL.md": b"---\nname: two\n---\n"})
    odd = tuple(
        SourceFile(path=path, size=10, mtime_ns=0, regular=True)
        for path in (
            "plugin/demo/skills/foo\n/SKILL.md",
            "plugin/demo/agents/bar\n.md",
            "plugin/demo\n/skills/baz/SKILL.md",
        )
    )
    sources = SkillSources(files=inputs.sources.files + odd)

    folded = build_catalog(
        CatalogInputs(
            project=inputs.project,
            project_plugin=inputs.project_plugin,
            sources=sources,
            texts=inputs.texts,
            lock=inputs.lock,
        )
    )

    assert [item.id for item in folded.catalog.items] == ["skill/demo/two"]
    assert catalog_reads(sources) == ("plugin/demo/skills/two/SKILL.md",)
    notice = folded.catalog.notice
    assert notice is not None
    assert "2 entries skipped" in notice
    assert "plugin/demo\n: skipped" in notice


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


def _codes(folded: FoldedCatalog, item: str) -> list[DiagnosticCode]:
    return [diagnostic.code for diagnostic in folded.details[item].diagnostics]


def test_links_uses_and_used_by_when_body_names_items() -> None:
    folded = build_catalog(_inputs(a_skills_fixture_tree()))

    alpha = folded.details["skill/hub-workflow/alpha"]
    evaluator = folded.details["agent/hub-workflow/evaluator"]
    beta = folded.details["skill/hub-workflow/beta"]
    assert [(r.kind, r.source, r.name) for r in alpha.uses] == [
        (ItemKind.AGENT, "hub-workflow", "evaluator"),
        (ItemKind.SKILL, "hub-workflow", "beta"),
    ]
    assert [r.id for r in evaluator.used_by] == ["skill/hub-workflow/alpha"]
    assert [r.id for r in beta.used_by] == ["skill/hub-workflow/alpha"]
    assert alpha.structure is not None
    assert [step.title for step in alpha.structure.steps] == ["Review", "Next"]
    assert [entry.text for entry in alpha.toc] == ["Alpha", "Steps"]
    assert alpha.context_cost is not None
    assert alpha.context_cost.on_invoke_tokens > 0
    assert evaluator.tools == ("Read", "Grep")
    assert evaluator.model == "sonnet"


def test_lists_bundled_files_when_skill_folder_holds_them() -> None:
    tree = a_skills_fixture_tree()
    tree["plugin/hub-workflow/skills/alpha/assets/out"] = Link("../../../../../../etc")
    tree["plugin/hub-workflow/skills/alpha/assets/pipe"] = Fifo()
    folded = build_catalog(_inputs(tree))

    alpha = folded.details["skill/hub-workflow/alpha"]
    assert [(f.path, f.role, f.link) for f in alpha.files] == [
        ("assets/out", "assets", True),
        ("references/r.md", "references", False),
        ("scripts/s.sh", "scripts", False),
    ]
    reference = alpha.files[1]
    assert reference.id == file_id("plugin/hub-workflow/skills/alpha/references/r.md")
    assert folded.files[alpha.id][reference.id] == (
        "plugin/hub-workflow/skills/alpha/references/r.md"
    )
    assert DiagnosticCode.LINK_OUTSIDE_HUB in _codes(folded, alpha.id)
    assert DiagnosticCode.NOT_REGULAR in _codes(folded, alpha.id)
    assert "etc" not in " ".join(d.message for d in alpha.diagnostics)
    assert folded.files.get("skill/hub-workflow/beta", {}) == {}


def test_reports_not_linked_when_project_skill_unlinked() -> None:
    folded = build_catalog(_inputs(a_skills_fixture_tree()))
    tree = a_skills_fixture_tree()
    tree[".claude/skills/gamma"] = Link("../../plugin/demo/skills/gamma")
    linked = build_catalog(_inputs(tree))

    assert DiagnosticCode.NOT_LINKED in _codes(folded, "skill/demo/gamma")
    assert DiagnosticCode.NOT_LINKED in _codes(folded, "agent/demo/scout")
    not_linked = folded.details["skill/demo/gamma"].diagnostics[-1]
    assert not_linked.message == "not linked yet: run hub sync"
    assert DiagnosticCode.NOT_LINKED not in _codes(folded, "skill/extra/delta")
    assert DiagnosticCode.NOT_LINKED not in _codes(linked, "skill/demo/gamma")
    assert linked.details["skill/demo/gamma"].linked_from == (".claude/skills/gamma",)


def test_reports_modified_when_sha_differs_from_lock() -> None:
    tree = a_skills_fixture_tree()
    tree["plugin/hub-workflow/skills/alpha/SKILL.md"] += b"\nEdited by hand.\n"
    tree["plugin/hub-workflow/hooks/hooks.json"] = b'{"hooks": {}}\n'
    folded = build_catalog(_inputs(tree))

    assert DiagnosticCode.MODIFIED_SINCE_SYNC in _codes(folded, "skill/hub-workflow/alpha")
    assert DiagnosticCode.MODIFIED_SINCE_SYNC not in _codes(folded, "skill/hub-workflow/beta")
    unchanged = build_catalog(_inputs(a_skills_fixture_tree()))
    assert all(
        DiagnosticCode.MODIFIED_SINCE_SYNC not in _codes(unchanged, item)
        for item in unchanged.details
    )
    alpha = folded.details["skill/hub-workflow/alpha"]
    assert alpha.lock is not None
    assert alpha.lock.ownership == "managed"


def test_reports_modified_hooks_when_hooks_json_differs_from_lock() -> None:
    tree = a_skills_fixture_tree()
    tree["plugin/hub-workflow/hooks/hooks.json"] += b"\n"
    folded = build_catalog(_inputs(tree))

    assert _codes(folded, "hook/hub-workflow/hub-workflow-stop-1") == [
        DiagnosticCode.MODIFIED_SINCE_SYNC
    ]


def test_lists_every_source_when_names_collide() -> None:
    tree = a_skills_fixture_tree()
    tree["plugin/demo/skills/alpha/SKILL.md"] = b"---\nname: alpha\ndescription: Again.\n---\n"
    folded = build_catalog(_inputs(tree))

    ours = folded.details["skill/hub-workflow/alpha"]
    theirs = folded.details["skill/demo/alpha"]
    duplicate = [d for d in ours.diagnostics if d.code is DiagnosticCode.DUPLICATE_NAME]
    assert len(duplicate) == 1
    assert "skill/demo/alpha" in duplicate[0].message
    assert DiagnosticCode.DUPLICATE_NAME in _codes(folded, theirs.id)
    assert DiagnosticCode.NOT_LINKED not in _codes(folded, theirs.id)
    beta = folded.details["skill/hub-workflow/beta"]
    assert sorted(r.id for r in beta.used_by) == ["skill/hub-workflow/alpha"]
    evaluator = folded.details["agent/hub-workflow/evaluator"]
    assert [r.id for r in evaluator.used_by] == ["skill/hub-workflow/alpha"]


def test_diagnoses_document_when_frontmatter_breaks_rules() -> None:
    tree: dict[str, TreeEntry] = {
        "plugin/extra/skills/named/SKILL.md": (
            b"---\nname: other-name\ncolour: red\n---\nAsk the `ghost` agent, then `/missing`.\n"
        ),
        "plugin/extra/skills/broken/SKILL.md": b"---\nname: &anchor broken\n---\n",
    }
    folded = build_catalog(_inputs(tree))

    assert _codes(folded, "skill/extra/named") == [
        DiagnosticCode.NAME_MISMATCH,
        DiagnosticCode.DESCRIPTION_MISSING,
        DiagnosticCode.REFERENCE_NOT_FOUND,
        DiagnosticCode.REFERENCE_NOT_FOUND,
        DiagnosticCode.UNKNOWN_KEY,
    ]
    assert _codes(folded, "skill/extra/broken") == [DiagnosticCode.FRONTMATTER_UNPARSEABLE]
    assert folded.details["skill/extra/broken"].uses == ()
    named = folded.details["skill/extra/named"]
    assert [(pair.key, pair.known) for pair in named.frontmatter] == [
        ("name", True),
        ("colour", False),
    ]
    assert _item(folded.catalog, named.id).diagnostics_count == len(named.diagnostics)
