"""Publish a Studio draft (AGH-295, D10, D19, D21, D24, S4, S5, A2, A5, A7, A8, A12-A18, A20;
AC-295.11-16): the hand edit is recorded first, the draft lands where the publish rules say under
one lock, a ``publish`` version naming the draft is recorded, then the draft is removed; an equal
draft writes and records nothing and removes the draft; a draft a version already names as its
``publish`` is spent (nothing written, recorded or removed); a retry with no version naming the
draft refuses what it cannot tell apart, a merge past the bounds is refused, a rename records its
``publish`` before removing the old unit."""

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Final

import pytest

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry
from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.item_versions.hub_item_writer import HubItemWriteError, ItemWriteRefusedError
from agent_hub.core.item_versions.item_version import (
    ItemVersion,
    ItemVersionMeta,
    NewItemVersion,
    VersionAuthor,
    VersionOrigin,
)
from agent_hub.core.item_versions.item_version_ports import MarkedUnit, ToolkitRef
from agent_hub.core.item_versions.publish_draft import DraftNotRemovedError, PublishDraft
from agent_hub.core.item_versions.publish_rules import DraftInvalidError
from agent_hub.core.item_versions.record_and_write import (
    ItemWrittenUnrecordedError,
    RecordAndWrite,
)
from agent_hub.core.item_versions.unit_content import MAX_UNIT_FILES
from agent_hub.core.item_versions.unit_hash import file_hash
from agent_hub.core.json_form import dump_json
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_reads import SkillReads
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES
from agent_hub.core.skills.skill_view import ItemKind, SkillCatalog, SkillDetail, SkillUsage
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.core.testing.item_version_fakes import FakeHubItemWriter, InMemoryItemVersionStore
from agent_hub.core.testing.skill_trees import FIXTURE_PLATFORM_VERSION

HUB: Final = "/hubs/demo-hub"
PROJECT: Final = "demo"
NOW: Final = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
AUTHOR: Final = VersionAuthor(name="Dev One", email="dev@example.com")
SCOUT: Final = "plugin/demo/agents/scout.md"
ALPHA: Final = "plugin/demo/skills/alpha"
SETTINGS: Final = ".claude/settings.json"
PLUGIN_HOOKS: Final = "plugin/demo/hooks/hooks.json"
SCRIPT: Final = "plugin/demo/scripts/check.sh"
# A synthetic GitHub token, built from fragments so no format-valid secret is one literal.
SYNTHETIC_TOKEN: Final = "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def _named(name: str, body: str = "Body.\n") -> bytes:
    return f"---\nname: {name}\ndescription: Does a thing.\n---\n{body}".encode()


def _hooks(event: str, command: str, matcher: str | None = None) -> bytes:
    group: dict[str, object] = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        group["matcher"] = matcher
    return json.dumps({"hooks": {event: [group]}}).encode()


class _Catalog:
    """``SkillReads`` over one fixed hub, as ``HubReadModels`` answers for the project."""

    def __init__(self, reads: SkillReads) -> None:
        self._reads = reads
        self.catalog_reads = 0

    def project_hubs(self) -> Iterator[tuple[str, str]]:
        return iter([(PROJECT, HUB)])

    def skill_catalog(self, project: str) -> SkillCatalog:
        self.catalog_reads += 1
        return self._reads.catalog(project=project, hub_path=HUB)

    def skill_item_names(self, project: str) -> frozenset[tuple[ItemKind, str]]:
        return self._reads.item_names(project=project, hub_path=HUB)

    def skill_detail(self, project: str, *, kind: ItemKind, source: str, name: str) -> SkillDetail:
        return self._reads.detail(
            project=project, hub_path=HUB, kind=kind, source=source, name=name
        )

    def marked_skill_unit(
        self, project: str, *, kind: ItemKind, source: str, name: str
    ) -> MarkedUnit | None:
        return self._reads.marked_unit(project, HUB, kind=kind, source=source, name=name)


class _Usage:
    """A usage source that counts the times it is asked."""

    def __init__(self) -> None:
        self.asked = 0

    def skill_usage(self, project: str) -> SkillUsage:
        del project
        self.asked += 1
        return SkillUsage(since=NOW, by_skill={}, by_agent={})


class _Rig:
    def __init__(
        self, files: dict[str, bytes], *, store: InMemoryItemVersionStore | None = None
    ) -> None:
        self.hub = FakeHub(skill_files=dict(files))
        reader = FakeHubFileReader({HUB: self.hub})
        self.store = store if store is not None else InMemoryItemVersionStore()
        self.capture = CaptureItemVersions(self.store, reader, lambda: NOW)
        self.writer = FakeHubItemWriter({HUB: self.hub})
        self.usage = _Usage()
        self.catalog = _Catalog(SkillReads(reader, self.usage, capture=self.capture))
        step = RecordAndWrite(
            self.store,
            reader=reader,
            writer=self.writer,
            author_of=lambda _project: AUTHOR,
            clock=lambda: NOW,
            capture=self.capture,
        )
        self.publish = PublishDraft(
            step,
            writer=self.writer,
            reader=reader,
            toolkit_units=self.catalog,
            catalog=self.catalog,
        )

    def draft(self, draft_id: str, files: dict[str, bytes]) -> None:
        for path, content in files.items():
            self.hub.skill_files[f".hub-drafts/{draft_id}/{path}"] = content

    def drafts(self) -> list[str]:
        return sorted(path for path in self.hub.skill_files if path.startswith(".hub-drafts/"))

    def origins(self, unit_path: str) -> list[VersionOrigin]:
        return [version.origin for version in reversed(self.store.page(PROJECT, unit_path))]


def _ref(kind: ItemKind, source: str, name: str) -> ToolkitRef:
    return ToolkitRef(project=PROJECT, kind=kind, source=source, name=name)


SCOUT_REF: Final = _ref(ItemKind.AGENT, "demo", "scout")


def test_records_external_then_publish_when_hand_edited() -> None:
    rig = _Rig({SCOUT: _named("scout", "One.\n")})
    rig.catalog.skill_catalog(PROJECT)
    rig.hub.skill_files[SCOUT] = _named("scout", "Edited by hand.\n")
    rig.draft("agent-abc123", {"scout.md": _named("scout", "Published.\n")})

    result = rig.publish.publish(PROJECT, "agent-abc123", SCOUT_REF, confirm_managed=False)

    assert rig.hub.skill_files[SCOUT] == _named("scout", "Published.\n")
    versions = list(reversed(rig.store.page(PROJECT, SCOUT)))
    assert [(v.origin, v.content_hash) for v in versions] == [
        (VersionOrigin.EXTERNAL, file_hash(_named("scout", "One.\n"))),
        (VersionOrigin.EXTERNAL, file_hash(_named("scout", "Edited by hand.\n"))),
        (VersionOrigin.PUBLISH, file_hash(_named("scout", "Published.\n"))),
    ]
    assert (versions[-1].author, versions[-1].draft_id) == (AUTHOR, "agent-abc123")
    assert (result.changed, result.versioned) == (True, True)
    assert rig.drafts() == []


def test_first_version_is_publish_when_new_item() -> None:
    rig = _Rig({})
    rig.draft("skill-new001", {"SKILL.md": _named("changelog"), "references/r.md": b"# R\n"})

    result = rig.publish.publish(PROJECT, "skill-new001", None, confirm_managed=False)

    unit = "plugin/demo/skills/changelog"
    assert rig.hub.skill_files[f"{unit}/SKILL.md"] == _named("changelog")
    assert rig.hub.skill_files[f"{unit}/references/r.md"] == b"# R\n"
    versions = rig.store.page(PROJECT, unit)
    assert [(v.origin, v.first, v.draft_id) for v in versions] == [
        (VersionOrigin.PUBLISH, True, "skill-new001")
    ]
    assert result.version is not None
    assert result.version.first
    assert rig.drafts() == []


def test_refuses_existing_new_item_when_name_taken() -> None:
    reviewer = ".claude/agents/reviewer.md"
    rig = _Rig({reviewer: _named("reviewer")})
    rig.draft("agent-new001", {"reviewer.md": _named("reviewer", "Mine.\n")})

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "agent-new001", None, confirm_managed=False)

    assert refused.value.code == "item_exists"
    assert "plugin/demo/agents/reviewer.md" not in rig.hub.skill_files
    assert rig.store.last(PROJECT, "plugin/demo/agents/reviewer.md") is None
    assert rig.drafts() == [".hub-drafts/agent-new001/reviewer.md"]


def test_moves_skill_with_hidden_entries_when_renamed() -> None:
    rig = _Rig(
        {
            f"{ALPHA}/SKILL.md": _named("alpha"),
            f"{ALPHA}/references/keep.md": b"# Keep\n",
            f"{ALPHA}/.cache/data": b"cached",
        }
    )
    rig.draft("skill-ren001", {"SKILL.md": _named("alpha2")})

    result = rig.publish.publish(
        PROJECT, "skill-ren001", _ref(ItemKind.SKILL, "demo", "alpha"), confirm_managed=False
    )

    renamed = "plugin/demo/skills/alpha2"
    assert {p: c for p, c in rig.hub.skill_files.items() if p.startswith("plugin/")} == {
        f"{renamed}/SKILL.md": _named("alpha2"),
        f"{renamed}/references/keep.md": b"# Keep\n",
        f"{renamed}/.cache/data": b"cached",
    }
    assert rig.origins(ALPHA) == [VersionOrigin.EXTERNAL]
    assert rig.origins(renamed) == [VersionOrigin.PUBLISH]
    assert result.changed
    assert rig.drafts() == []


def test_refuses_rename_when_name_taken() -> None:
    rig = _Rig(
        {
            f"{ALPHA}/SKILL.md": _named("alpha"),
            "plugin/demo/skills/beta/notes.md": b"# no SKILL.md, still a folder\n",
        }
    )
    rig.draft("skill-ren002", {"SKILL.md": _named("beta")})

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(
            PROJECT, "skill-ren002", _ref(ItemKind.SKILL, "demo", "alpha"), confirm_managed=False
        )

    assert refused.value.code == "item_exists"
    assert rig.hub.skill_files[f"{ALPHA}/SKILL.md"] == _named("alpha")
    assert rig.writer.writes == []


def test_refuses_draft_when_kind_differs_from_target() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    rig.draft("skill-kind01", {"SKILL.md": _named("scout")})

    with pytest.raises(DraftInvalidError):
        rig.publish.publish(PROJECT, "skill-kind01", SCOUT_REF, confirm_managed=False)
    with pytest.raises(EntityNotFoundError):
        rig.publish.publish(
            PROJECT, "skill-kind01", _ref(ItemKind.AGENT, "demo", "ghost"), confirm_managed=False
        )

    assert rig.writer.writes == []


def test_unversioned_secret_when_published_file_matches() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    secret = _named("scout", f"token: {SYNTHETIC_TOKEN}\n")
    rig.draft("agent-sec001", {"scout.md": secret})

    result = rig.publish.publish(PROJECT, "agent-sec001", SCOUT_REF, confirm_managed=False)

    assert rig.hub.skill_files[SCOUT] == secret
    assert (result.changed, result.versioned, result.reason) == (True, False, "secret")
    assert rig.origins(SCOUT) == [VersionOrigin.EXTERNAL]
    assert rig.drafts() == []


def test_removes_draft_when_equal() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    rig.draft("agent-eq0001", {"scout.md": _named("scout")})

    result = rig.publish.publish(PROJECT, "agent-eq0001", SCOUT_REF, confirm_managed=False)

    assert (result.changed, result.versioned, result.version) == (False, False, None)
    assert rig.writer.writes == [(HUB, ".hub-drafts/agent-eq0001")]
    assert rig.store.last(PROJECT, SCOUT) is None
    assert rig.drafts() == []


def test_reports_draft_not_removed_when_removal_fails() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    rig.draft("agent-rm0001", {"scout.md": _named("scout", "New.\n")})
    rig.writer.fail_on.add(".hub-drafts/agent-rm0001")

    with pytest.raises(DraftNotRemovedError) as failed:
        rig.publish.publish(PROJECT, "agent-rm0001", SCOUT_REF, confirm_managed=False)

    assert failed.value.result.changed
    assert rig.hub.skill_files[SCOUT] == _named("scout", "New.\n")
    assert rig.drafts() == [".hub-drafts/agent-rm0001/scout.md"]


def test_merges_hooks_and_writes_scripts_when_new_hook() -> None:
    rig = _Rig({PLUGIN_HOOKS: _hooks("Stop", "kept")})
    rig.draft(
        "hook-new001",
        {"hooks.json": _hooks("PreToolUse", "check", "Bash"), "scripts/check.sh": b"#!/bin/sh\n"},
    )
    rig.hub.executable = frozenset({".hub-drafts/hook-new001/scripts/check.sh"})

    result = rig.publish.publish(PROJECT, "hook-new001", None, confirm_managed=False)

    assert json.loads(rig.hub.skill_files[PLUGIN_HOOKS])["hooks"] == {
        "Stop": [{"hooks": [{"type": "command", "command": "kept"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "check"}]}],
    }
    assert rig.hub.skill_files[SCRIPT] == b"#!/bin/sh\n"
    assert SCRIPT in rig.hub.executable
    assert [w[1] for w in rig.writer.writes[:2]] == [SCRIPT, PLUGIN_HOOKS]
    assert rig.origins(PLUGIN_HOOKS) == [VersionOrigin.EXTERNAL, VersionOrigin.PUBLISH]
    assert result.changed
    assert rig.drafts() == []


def test_refuses_changed_script_when_hooks_file_equal() -> None:
    hook = _hooks("PreToolUse", "check", "Bash")
    rig = _Rig({PLUGIN_HOOKS: hook, SCRIPT: b"#!/bin/sh\necho old\n"})
    rig.draft("hook-new002", {"hooks.json": hook, "scripts/check.sh": b"#!/bin/sh\necho new\n"})

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "hook-new002", None, confirm_managed=False)

    assert refused.value.code == "item_exists"
    assert rig.hub.skill_files[SCRIPT] == b"#!/bin/sh\necho old\n"
    assert rig.drafts() != []


def _secret_hooks(event: str) -> bytes:
    return _hooks(event, f"notify --token {SYNTHETIC_TOKEN}")


def test_refuses_moved_hook_when_retried_without_version() -> None:
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "one"}]},
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "two"}]},
            ],
        }
    }
    rig = _Rig({SETTINGS: json.dumps(settings).encode()})
    rig.draft("hook-mov002", {"hooks.json": _secret_hooks("Stop")})
    rig.writer.fail_on.add(".hub-drafts/hook-mov002")
    ref = _ref(ItemKind.HOOK, "settings", "settings-pretooluse-1")
    with pytest.raises(DraftNotRemovedError) as first:
        rig.publish.publish(PROJECT, "hook-mov002", ref, confirm_managed=False)
    assert first.value.result.reason == "secret"
    once = rig.hub.skill_files[SETTINGS]
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "hook-mov002", ref, confirm_managed=False)

    assert refused.value.code == "item_exists"
    # A17: the answer claims no earlier publish.
    assert refused.value.reason == "The hooks file already holds this draft's hooks"
    assert rig.hub.skill_files[SETTINGS] == once
    assert rig.writer.writes == []
    assert rig.drafts() == [".hub-drafts/hook-mov002/hooks.json"]


def test_keeps_hook_in_place_when_draft_equal_to_hook() -> None:
    hook = dump_json(json.loads(_hooks("PreToolUse", "one", "Bash")))
    rig = _Rig({SETTINGS: hook})
    rig.draft("hook-eq0001", {"hooks.json": hook})
    ref = _ref(ItemKind.HOOK, "settings", "settings-pretooluse-1")

    result = rig.publish.publish(PROJECT, "hook-eq0001", ref, confirm_managed=False)

    assert not result.changed
    assert rig.hub.skill_files[SETTINGS] == hook
    assert rig.drafts() == []


def test_refuses_spent_draft_when_renamed_skill_retried_with_old_item_gone() -> None:
    rig = _Rig({f"{ALPHA}/SKILL.md": _named("alpha")})
    rig.draft("skill-ren003", {"SKILL.md": _named("alpha2")})
    rig.writer.fail_on.add(".hub-drafts/skill-ren003")
    alpha = _ref(ItemKind.SKILL, "demo", "alpha")
    with pytest.raises(DraftNotRemovedError):
        rig.publish.publish(PROJECT, "skill-ren003", alpha, confirm_managed=False)
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "skill-ren003", alpha, confirm_managed=False)

    # A20 comes first: the old item being gone is not what answers.
    assert refused.value.code == "draft_already_published"
    assert rig.writer.writes == []
    assert rig.origins("plugin/demo/skills/alpha2") == [VersionOrigin.PUBLISH]
    assert rig.drafts() == [".hub-drafts/skill-ren003/SKILL.md"]


def test_answers_not_found_when_unversioned_rename_retried_with_old_item_gone() -> None:
    renamed = "plugin/demo/skills/alpha2"
    rig = _Rig({f"{ALPHA}/SKILL.md": _named("alpha")})
    rig.draft("skill-ren010", {"SKILL.md": _named("alpha2", f"token: {SYNTHETIC_TOKEN}\n")})
    rig.writer.fail_on.add(".hub-drafts/skill-ren010")
    alpha = _ref(ItemKind.SKILL, "demo", "alpha")
    with pytest.raises(DraftNotRemovedError) as first:
        rig.publish.publish(PROJECT, "skill-ren010", alpha, confirm_managed=False)
    assert first.value.result.reason == "secret"
    assert f"{ALPHA}/SKILL.md" not in rig.hub.skill_files
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    # A12: no version names the draft, so the gone old item answers.
    with pytest.raises(EntityNotFoundError):
        rig.publish.publish(PROJECT, "skill-ren010", alpha, confirm_managed=False)

    assert rig.writer.writes == []
    assert rig.store.last(PROJECT, renamed) is None
    assert rig.drafts() == [".hub-drafts/skill-ren010/SKILL.md"]


def test_refuses_new_item_when_retried_without_version() -> None:
    rig = _Rig({})
    secret = _named("planner", f"token: {SYNTHETIC_TOKEN}\n")
    rig.draft("agent-new004", {"planner.md": secret})
    rig.writer.fail_on.add(".hub-drafts/agent-new004")
    with pytest.raises(DraftNotRemovedError) as first:
        rig.publish.publish(PROJECT, "agent-new004", None, confirm_managed=False)
    assert first.value.result.reason == "secret"
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "agent-new004", None, confirm_managed=False)

    assert refused.value.code == "item_exists"
    assert rig.writer.writes == []


def _past_bounds(event: str) -> bytes:
    document = json.loads(_hooks(event, "big"))
    document["padding"] = "x" * MAX_SKILL_FILE_BYTES
    return json.dumps(document).encode()


def test_refuses_hook_edit_when_file_past_bounds() -> None:
    big = _past_bounds("PreToolUse")
    rig = _Rig({SETTINGS: big})
    rig.draft("hook-big001", {"hooks.json": _hooks("PreToolUse", "small")})
    ref = _ref(ItemKind.HOOK, "settings", "settings-pretooluse-1")

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "hook-big001", ref, confirm_managed=False)

    assert refused.value.code == "unit_unreadable"
    assert rig.hub.skill_files[SETTINGS] == big
    assert rig.writer.writes == []
    assert rig.store.last(PROJECT, SETTINGS) is None


def test_refuses_new_hook_when_hooks_file_past_bounds() -> None:
    big = _past_bounds("Stop")
    rig = _Rig({PLUGIN_HOOKS: big})
    rig.draft(
        "hook-big002", {"hooks.json": _hooks("PreToolUse", "check"), "scripts/check.sh": b"x\n"}
    )

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "hook-big002", None, confirm_managed=False)

    assert refused.value.code == "unit_unreadable"
    assert rig.hub.skill_files[PLUGIN_HOOKS] == big
    assert SCRIPT not in rig.hub.skill_files
    assert rig.writer.writes == []


def test_answers_script_only_when_only_scripts_written() -> None:
    hook = dump_json(json.loads(_hooks("PreToolUse", "check", "Bash")))
    rig = _Rig({PLUGIN_HOOKS: hook})
    rig.draft("hook-new005", {"hooks.json": hook, "scripts/check.sh": b"#!/bin/sh\n"})

    result = rig.publish.publish(PROJECT, "hook-new005", None, confirm_managed=False)

    assert (result.changed, result.versioned, result.reason) == (True, False, "script_only")
    assert result.version is None
    assert rig.hub.skill_files[SCRIPT] == b"#!/bin/sh\n"
    assert rig.hub.skill_files[PLUGIN_HOOKS] == hook
    assert rig.drafts() == []


def test_records_publish_before_removing_old_when_renamed() -> None:
    rig = _Rig({f"{ALPHA}/SKILL.md": _named("alpha")})
    rig.draft("skill-ren004", {"SKILL.md": _named("alpha2")})
    rig.writer.fail_on.add(ALPHA)

    with pytest.raises(HubItemWriteError) as failed:
        rig.publish.publish(
            PROJECT, "skill-ren004", _ref(ItemKind.SKILL, "demo", "alpha"), confirm_managed=False
        )

    # A18: its own failure kind, naming no path.
    assert failed.value.kind == "old_not_removed"
    assert "alpha" not in str(failed.value)
    renamed = "plugin/demo/skills/alpha2"
    assert rig.hub.skill_files[f"{ALPHA}/SKILL.md"] == _named("alpha")
    assert rig.hub.skill_files[f"{renamed}/SKILL.md"] == _named("alpha2")
    assert rig.origins(renamed) == [VersionOrigin.PUBLISH]
    assert rig.origins(ALPHA) == [VersionOrigin.EXTERNAL]
    assert rig.drafts() == [".hub-drafts/skill-ren004/SKILL.md"]


def test_refuses_hook_edit_draft_when_it_carries_scripts() -> None:
    rig = _Rig({PLUGIN_HOOKS: _hooks("PreToolUse", "check", "Bash")})
    rig.draft(
        "hook-scr001",
        {"hooks.json": _hooks("PreToolUse", "check2", "Bash"), "scripts/check.sh": b"x\n"},
    )
    ref = _ref(ItemKind.HOOK, "demo", "demo-pretooluse-1")

    with pytest.raises(DraftInvalidError):
        rig.publish.publish(PROJECT, "hook-scr001", ref, confirm_managed=False)

    assert rig.writer.writes == []
    assert SCRIPT not in rig.hub.skill_files
    assert rig.store.last(PROJECT, PLUGIN_HOOKS) is None


class _EditedAtLock(FakeHubItemWriter):
    """A writer whose first ``is_writable`` (the step's first act under its lock) stands in for
    a hand edit landing between the item's resolve and the lock."""

    def __init__(self, rig: _Rig, path: str, content: bytes | None) -> None:
        super().__init__(rig.writer.hubs)
        self._edit: tuple[str, bytes | None] | None = (path, content)

    def is_writable(self, hub_path: str, unit_paths: Sequence[str] = ()) -> bool:
        if self._edit is not None and unit_paths:
            path, content = self._edit
            if content is None:
                del self.hubs[hub_path].skill_files[path]
            else:
                self.hubs[hub_path].skill_files[path] = content
            self._edit = None
        return super().is_writable(hub_path, unit_paths)


def test_locates_hook_in_file_read_under_lock_when_edited_before_lock() -> None:
    rig = _Rig({SETTINGS: _hooks("PreToolUse", "one", "Bash")})
    publish = _edited_at_lock(rig, SETTINGS, _hooks("pretooluse", "by hand", "Bash"))
    rig.draft("hook-lck001", {"hooks.json": _hooks("pretooluse", "published", "Bash")})
    ref = _ref(ItemKind.HOOK, "settings", "settings-pretooluse-1")

    result = publish.publish(PROJECT, "hook-lck001", ref, confirm_managed=False)

    assert result.changed
    assert json.loads(rig.hub.skill_files[SETTINGS]) == json.loads(
        _hooks("pretooluse", "published", "Bash")
    )
    assert rig.origins(SETTINGS) == [VersionOrigin.EXTERNAL, VersionOrigin.PUBLISH]


def _edited_at_lock(rig: _Rig, path: str, content: bytes | None) -> PublishDraft:
    writer = _EditedAtLock(rig, path, content)
    reader = FakeHubFileReader({HUB: rig.hub})
    step = RecordAndWrite(
        rig.store,
        reader=reader,
        writer=writer,
        author_of=lambda _project: AUTHOR,
        clock=lambda: NOW,
        capture=rig.capture,
    )
    return PublishDraft(
        step, writer=writer, reader=reader, toolkit_units=rig.catalog, catalog=rig.catalog
    )


def test_answers_not_found_when_hook_gone_before_lock() -> None:
    rig = _Rig({SETTINGS: _hooks("PreToolUse", "one", "Bash")})
    gone = _hooks("Stop", "other")
    publish = _edited_at_lock(rig, SETTINGS, gone)
    rig.draft("hook-gon001", {"hooks.json": _hooks("PreToolUse", "published", "Bash")})
    ref = _ref(ItemKind.HOOK, "settings", "settings-pretooluse-1")

    with pytest.raises(EntityNotFoundError):
        publish.publish(PROJECT, "hook-gon001", ref, confirm_managed=False)

    assert rig.hub.skill_files[SETTINGS] == gone
    assert rig.drafts() == [".hub-drafts/hook-gon001/hooks.json"]


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (".claude/settings.project.json", "settings-project"),
        (PLUGIN_HOOKS, "demo"),
    ],
)
def test_replaces_hook_when_in_project_settings_or_plugin(path: str, source: str) -> None:
    rig = _Rig({path: _hooks("PreToolUse", "one", "Bash")})
    rig.draft("hook-src001", {"hooks.json": _hooks("PreToolUse", "published", "Bash")})
    ref = _ref(ItemKind.HOOK, source, f"{source}-pretooluse-1")

    result = rig.publish.publish(PROJECT, "hook-src001", ref, confirm_managed=False)

    assert result.versioned
    assert json.loads(rig.hub.skill_files[path]) == json.loads(
        _hooks("PreToolUse", "published", "Bash")
    )


def _command(command: str) -> dict[str, str]:
    return {"type": "command", "command": command}


def _three_hooks() -> bytes:
    group = {"matcher": "Bash", "hooks": [_command("x1"), _command("X"), _command("x3")]}
    return json.dumps({"hooks": {"PreToolUse": [group]}}).encode()


def _two_hook_draft(first: str) -> bytes:
    group = {"matcher": "Bash", "hooks": [_command(first), _command("B")]}
    return json.dumps({"hooks": {"PreToolUse": [group]}}).encode()


SECOND_HOOK: Final = _ref(ItemKind.HOOK, "settings", "settings-pretooluse-2")


def _commands(file_json: bytes) -> list[str]:
    groups = json.loads(file_json)["hooks"]["PreToolUse"]
    return [hook["command"] for group in groups for hook in group["hooks"]]


def test_answers_unchanged_when_spliced_hooks_retried_after_secret() -> None:
    rig = _Rig({SETTINGS: _three_hooks()})
    rig.draft("hook-spl001", {"hooks.json": _two_hook_draft(f"notify --token {SYNTHETIC_TOKEN}")})
    rig.writer.fail_on.add(".hub-drafts/hook-spl001")
    with pytest.raises(DraftNotRemovedError) as first:
        rig.publish.publish(PROJECT, "hook-spl001", SECOND_HOOK, confirm_managed=False)
    assert first.value.result.reason == "secret"
    once = rig.hub.skill_files[SETTINGS]
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    again = rig.publish.publish(PROJECT, "hook-spl001", SECOND_HOOK, confirm_managed=False)

    assert _commands(once) == ["x1", f"notify --token {SYNTHETIC_TOKEN}", "B", "x3"]
    assert (again.changed, again.versioned) == (False, False)
    assert rig.hub.skill_files[SETTINGS] == once
    assert rig.writer.writes == [(HUB, ".hub-drafts/hook-spl001")]
    assert rig.drafts() == []


class _PublishFailingStore(InMemoryItemVersionStore):
    """Fails every ``publish`` append as a busy database does, while ``failing``."""

    def __init__(self) -> None:
        super().__init__()
        self.failing = True

    def append(self, version: NewItemVersion) -> ItemVersion:
        if self.failing and version.origin is VersionOrigin.PUBLISH:
            raise _StoreBusyError("database is locked")
        return super().append(version)


class _StoreBusyError(AgentHubError):
    """Stands in for the storage adapter's busy database."""


def test_answers_unchanged_when_spliced_hooks_retried_after_unrecorded() -> None:
    store = _PublishFailingStore()
    rig = _Rig({SETTINGS: _three_hooks()}, store=store)
    rig.draft("hook-spl002", {"hooks.json": _two_hook_draft("A")})
    with pytest.raises(ItemWrittenUnrecordedError):
        rig.publish.publish(PROJECT, "hook-spl002", SECOND_HOOK, confirm_managed=False)
    once = rig.hub.skill_files[SETTINGS]
    store.failing = False
    rig.writer.writes.clear()

    again = rig.publish.publish(PROJECT, "hook-spl002", SECOND_HOOK, confirm_managed=False)

    assert _commands(once) == ["x1", "A", "B", "x3"]
    assert not again.changed
    assert rig.hub.skill_files[SETTINGS] == once
    assert rig.writer.writes == [(HUB, ".hub-drafts/hook-spl002")]
    assert rig.drafts() == []


def test_refuses_hook_draft_when_a_group_has_no_hooks() -> None:
    rig = _Rig({SETTINGS: _three_hooks()})
    draft = {
        "hooks": {
            "Stop": [{"hooks": [_command("stop")]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": []}],
        }
    }
    rig.draft("hook-emp001", {"hooks.json": json.dumps(draft).encode()})

    for _ in range(2):
        with pytest.raises(DraftInvalidError):
            rig.publish.publish(PROJECT, "hook-emp001", SECOND_HOOK, confirm_managed=False)

    assert rig.hub.skill_files[SETTINGS] == _three_hooks()
    assert rig.writer.writes == []
    assert rig.drafts() == [".hub-drafts/hook-emp001/hooks.json"]


def _managed(rig: _Rig, path: str) -> None:
    entry = ManagedFileEntry(ownership="managed", sha256="ab" * 32, executable=False)
    rig.hub.lock = HubLock(
        lock_version=1,
        platform_version=FIXTURE_PLATFORM_VERSION,
        schema_version=1,
        modules=(),
        files={path: entry},
    )


def test_refuses_managed_unit_when_publish_not_confirmed() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    _managed(rig, SCOUT)
    rig.draft("agent-man001", {"scout.md": _named("scout", "Published.\n")})

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "agent-man001", SCOUT_REF, confirm_managed=False)

    assert refused.value.code == "managed_confirmation_required"
    assert rig.hub.skill_files[SCOUT] == _named("scout")
    assert rig.writer.writes == []
    assert rig.drafts() == [".hub-drafts/agent-man001/scout.md"]


def test_writes_managed_unit_when_publish_confirmed() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    _managed(rig, SCOUT)
    rig.draft("agent-man002", {"scout.md": _named("scout", "Published.\n")})

    result = rig.publish.publish(PROJECT, "agent-man002", SCOUT_REF, confirm_managed=True)

    assert (result.changed, result.versioned) == (True, True)
    assert rig.hub.skill_files[SCOUT] == _named("scout", "Published.\n")
    assert rig.origins(SCOUT) == [VersionOrigin.EXTERNAL, VersionOrigin.PUBLISH]
    assert rig.drafts() == []


def test_keeps_old_unit_and_draft_when_rename_written_not_recorded() -> None:
    rig = _Rig({f"{ALPHA}/SKILL.md": _named("alpha")}, store=_PublishFailingStore())
    rig.draft("skill-ren006", {"SKILL.md": _named("alpha2")})

    with pytest.raises(ItemWrittenUnrecordedError):
        rig.publish.publish(
            PROJECT, "skill-ren006", _ref(ItemKind.SKILL, "demo", "alpha"), confirm_managed=False
        )

    assert rig.hub.skill_files[f"{ALPHA}/SKILL.md"] == _named("alpha")
    assert rig.hub.skill_files["plugin/demo/skills/alpha2/SKILL.md"] == _named("alpha2")
    assert rig.drafts() == [".hub-drafts/skill-ren006/SKILL.md"]


def test_skips_full_catalog_read_when_new_item_name_checked() -> None:
    reviewer = ".claude/agents/reviewer.md"
    rig = _Rig({reviewer: _named("reviewer")})
    rig.draft("skill-new007", {"SKILL.md": _named("changelog")})

    result = rig.publish.publish(PROJECT, "skill-new007", None, confirm_managed=False)

    assert result.changed
    assert rig.catalog.catalog_reads == 0
    assert rig.usage.asked == 0
    # No capture: the other items' units get no version from the name check.
    assert rig.store.last(PROJECT, reviewer) is None


_GONE_CASES: Final = {
    "agent": (SCOUT, SCOUT_REF, _named("scout"), {"scout.md": _named("scout", "New.\n")}),
    "hook": (
        SETTINGS,
        _ref(ItemKind.HOOK, "settings", "settings-pretooluse-1"),
        _hooks("PreToolUse", "one", "Bash"),
        {"hooks.json": _hooks("PreToolUse", "new", "Bash")},
    ),
}


@pytest.mark.parametrize("entity", sorted(_GONE_CASES))
def test_names_unit_kind_when_unit_gone_before_lock(entity: str) -> None:
    path, ref, content, files = _GONE_CASES[entity]
    rig = _Rig({path: content})
    publish = _edited_at_lock(rig, path, None)
    rig.draft(f"{entity}-gone01", files)

    with pytest.raises(EntityNotFoundError) as missing:
        publish.publish(PROJECT, f"{entity}-gone01", ref, confirm_managed=False)

    assert missing.value.entity == entity


def test_refuses_skill_edit_when_folder_past_file_bounds() -> None:
    files = {f"{ALPHA}/SKILL.md": _named("alpha")}
    files.update(
        {f"{ALPHA}/references/r{index:03d}.md": b"# R\n" for index in range(MAX_UNIT_FILES)}
    )
    rig = _Rig(files)
    rig.draft("skill-big001", {"SKILL.md": _named("alpha", "Edited.\n")})

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(
            PROJECT, "skill-big001", _ref(ItemKind.SKILL, "demo", "alpha"), confirm_managed=False
        )

    assert refused.value.code == "unit_unreadable"
    assert rig.hub.skill_files[f"{ALPHA}/SKILL.md"] == _named("alpha")
    assert rig.writer.writes == []


@pytest.mark.parametrize("code", ["link_in_path", "hub_read_only"])
def test_answers_old_not_removed_when_old_removal_refused(
    code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    renamed = "plugin/demo/skills/alpha2"
    rig = _Rig({f"{ALPHA}/SKILL.md": _named("alpha")})
    rig.draft("skill-ren009", {"SKILL.md": _named("alpha2")})

    def refuse(hub_path: str, unit_path: str, *, kind: object) -> None:
        del hub_path, unit_path, kind
        raise ItemWriteRefusedError(code)

    monkeypatch.setattr(rig.writer, "remove_unit", refuse)

    with pytest.raises(HubItemWriteError) as failed:
        rig.publish.publish(
            PROJECT, "skill-ren009", _ref(ItemKind.SKILL, "demo", "alpha"), confirm_managed=False
        )

    assert failed.value.kind == "old_not_removed"
    assert rig.hub.skill_files[f"{ALPHA}/SKILL.md"] == _named("alpha")
    assert rig.hub.skill_files[f"{renamed}/SKILL.md"] == _named("alpha2")
    assert rig.origins(renamed) == [VersionOrigin.PUBLISH]
    assert rig.drafts() == [".hub-drafts/skill-ren009/SKILL.md"]


def test_refuses_moved_hook_when_first_publish_finds_its_groups_held() -> None:
    settings = {
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [_command("one")]}],
            "Stop": [{"hooks": [_command("moved")]}],
        }
    }
    held = json.dumps(settings).encode()
    rig = _Rig({SETTINGS: held})
    rig.draft("hook-mov003", {"hooks.json": _hooks("Stop", "moved")})
    ref = _ref(ItemKind.HOOK, "settings", "settings-pretooluse-1")

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "hook-mov003", ref, confirm_managed=False)

    assert refused.value.code == "item_exists"
    assert refused.value.reason == "The hooks file already holds this draft's hooks"
    assert rig.hub.skill_files[SETTINGS] == held
    assert rig.writer.writes == []
    assert rig.store.last(PROJECT, SETTINGS) is None
    assert rig.drafts() == [".hub-drafts/hook-mov003/hooks.json"]


# A20: a draft some version of the project names as its publish is spent.
SPENT: Final = "This draft was already published; discard it"
RENAMED: Final = "plugin/demo/skills/alpha2"
GAMMA: Final = "plugin/demo/skills/gamma"


def _plugin_files(rig: _Rig) -> dict[str, bytes]:
    return {
        path: content
        for path, content in rig.hub.skill_files.items()
        if path.startswith(("plugin/", ".claude/"))
    }


# Every unit a spent-draft case can touch, so a refusal is seen to record nothing.
_SPENT_UNITS: Final = (
    SCOUT,
    ALPHA,
    RENAMED,
    GAMMA,
    SETTINGS,
    PLUGIN_HOOKS,
    "plugin/demo/agents/planner.md",
)


def _pages(rig: _Rig) -> dict[str, tuple[ItemVersionMeta, ...]]:
    return {path: rig.store.page(PROJECT, path, limit=200) for path in _SPENT_UNITS}


def _assert_spent(
    rig: _Rig,
    refused: pytest.ExceptionInfo[ItemWriteRefusedError],
    before: dict[str, tuple[ItemVersionMeta, ...]],
) -> None:
    assert refused.value.code == "draft_already_published"
    assert refused.value.reason == SPENT
    assert rig.writer.writes == []
    assert _pages(rig) == before


def test_refuses_spent_draft_when_agent_edit_retried_after_draft_not_removed() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    rig.draft("agent-spt001", {"scout.md": _named("scout", "New.\n")})
    rig.writer.fail_on.add(".hub-drafts/agent-spt001")
    with pytest.raises(DraftNotRemovedError):
        rig.publish.publish(PROJECT, "agent-spt001", SCOUT_REF, confirm_managed=False)
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    before = _pages(rig)
    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "agent-spt001", SCOUT_REF, confirm_managed=False)

    _assert_spent(rig, refused, before)
    assert rig.hub.skill_files[SCOUT] == _named("scout", "New.\n")
    assert rig.origins(SCOUT) == [VersionOrigin.EXTERNAL, VersionOrigin.PUBLISH]
    assert rig.drafts() == [".hub-drafts/agent-spt001/scout.md"]


def test_keeps_old_item_when_rename_retried_after_old_not_removed() -> None:
    rig = _Rig({f"{ALPHA}/SKILL.md": _named("alpha")})
    rig.draft("skill-spt002", {"SKILL.md": _named("alpha2")})
    rig.writer.fail_on.add(ALPHA)
    alpha = _ref(ItemKind.SKILL, "demo", "alpha")
    with pytest.raises(HubItemWriteError) as failed:
        rig.publish.publish(PROJECT, "skill-spt002", alpha, confirm_managed=False)
    assert failed.value.kind == "old_not_removed"
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    before = _pages(rig)
    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "skill-spt002", alpha, confirm_managed=False)

    _assert_spent(rig, refused, before)
    assert _plugin_files(rig) == {
        f"{ALPHA}/SKILL.md": _named("alpha"),
        f"{RENAMED}/SKILL.md": _named("alpha2"),
    }
    assert rig.origins(ALPHA) == [VersionOrigin.EXTERNAL]
    assert rig.origins(RENAMED) == [VersionOrigin.PUBLISH]
    assert rig.drafts() == [".hub-drafts/skill-spt002/SKILL.md"]


@pytest.mark.parametrize("edited", [False, True], ids=["kept", "edited_again"])
def test_refuses_spent_draft_when_hook_edit_retried_after_draft_not_removed(
    *, edited: bool
) -> None:
    rig = _Rig({SETTINGS: _three_hooks()})
    rig.draft("hook-spt003", {"hooks.json": _two_hook_draft("A")})
    rig.writer.fail_on.add(".hub-drafts/hook-spt003")
    with pytest.raises(DraftNotRemovedError):
        rig.publish.publish(PROJECT, "hook-spt003", SECOND_HOOK, confirm_managed=False)
    once = rig.hub.skill_files[SETTINGS]
    rig.writer.fail_on.clear()
    if edited:
        rig.draft("hook-spt003", {"hooks.json": _two_hook_draft("C")})
    rig.writer.writes.clear()

    before = _pages(rig)
    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "hook-spt003", SECOND_HOOK, confirm_managed=False)

    _assert_spent(rig, refused, before)
    assert _commands(once) == ["x1", "A", "B", "x3"]
    assert rig.hub.skill_files[SETTINGS] == once
    assert rig.origins(SETTINGS) == [VersionOrigin.EXTERNAL, VersionOrigin.PUBLISH]
    assert rig.drafts() == [".hub-drafts/hook-spt003/hooks.json"]


def test_refuses_spent_draft_when_new_item_retried_after_draft_not_removed() -> None:
    planner = "plugin/demo/agents/planner.md"
    rig = _Rig({})
    rig.draft("agent-spt004", {"planner.md": _named("planner")})
    rig.writer.fail_on.add(".hub-drafts/agent-spt004")
    with pytest.raises(DraftNotRemovedError):
        rig.publish.publish(PROJECT, "agent-spt004", None, confirm_managed=False)
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    before = _pages(rig)
    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "agent-spt004", None, confirm_managed=False)

    _assert_spent(rig, refused, before)
    assert rig.hub.skill_files[planner] == _named("planner")
    assert rig.origins(planner) == [VersionOrigin.PUBLISH]
    assert rig.drafts() == [".hub-drafts/agent-spt004/planner.md"]


def test_keeps_other_target_when_spent_rename_draft_published_onto_it() -> None:
    rig = _Rig({f"{ALPHA}/SKILL.md": _named("alpha"), f"{GAMMA}/SKILL.md": _named("gamma")})
    rig.draft("skill-spt005", {"SKILL.md": _named("alpha2")})
    rig.writer.fail_on.add(".hub-drafts/skill-spt005")
    with pytest.raises(DraftNotRemovedError):
        rig.publish.publish(
            PROJECT, "skill-spt005", _ref(ItemKind.SKILL, "demo", "alpha"), confirm_managed=False
        )
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()

    before = _pages(rig)
    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(
            PROJECT, "skill-spt005", _ref(ItemKind.SKILL, "demo", "gamma"), confirm_managed=False
        )

    _assert_spent(rig, refused, before)
    assert _plugin_files(rig) == {
        f"{RENAMED}/SKILL.md": _named("alpha2"),
        f"{GAMMA}/SKILL.md": _named("gamma"),
    }
    assert rig.store.last(PROJECT, GAMMA) is None
    assert rig.drafts() == [".hub-drafts/skill-spt005/SKILL.md"]


def _spent_scout(rig: _Rig, draft_id: str) -> None:
    rig.draft(draft_id, {"scout.md": _named("scout", "New.\n")})
    rig.writer.fail_on.add(f".hub-drafts/{draft_id}")
    with pytest.raises(DraftNotRemovedError):
        rig.publish.publish(PROJECT, draft_id, SCOUT_REF, confirm_managed=False)
    rig.writer.fail_on.clear()
    rig.writer.writes.clear()


def test_refuses_spent_draft_when_aimed_at_target_of_other_kind() -> None:
    rig = _Rig({SCOUT: _named("scout"), f"{ALPHA}/SKILL.md": _named("alpha")})
    _spent_scout(rig, "agent-spt006")

    before = _pages(rig)
    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(
            PROJECT, "agent-spt006", _ref(ItemKind.SKILL, "demo", "alpha"), confirm_managed=False
        )

    _assert_spent(rig, refused, before)
    assert rig.hub.skill_files[f"{ALPHA}/SKILL.md"] == _named("alpha")
    assert rig.drafts() == [".hub-drafts/agent-spt006/scout.md"]


def test_refuses_spent_draft_when_kept_draft_edited_into_invalid_one() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    _spent_scout(rig, "agent-spt007")
    rig.draft("agent-spt007", {"scout.md": b"no frontmatter\n"})

    before = _pages(rig)
    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "agent-spt007", SCOUT_REF, confirm_managed=False)

    _assert_spent(rig, refused, before)
    assert rig.hub.skill_files[SCOUT] == _named("scout", "New.\n")
    assert rig.drafts() == [".hub-drafts/agent-spt007/scout.md"]


def test_refuses_spent_draft_when_kept_folder_read_refused() -> None:
    rig = _Rig({SCOUT: _named("scout")})
    _spent_scout(rig, "agent-spt008")
    # The kept folder now reads as a link: a read would refuse it, the spent check answers first.
    rig.hub.skill_links[".hub-drafts/agent-spt008"] = "/elsewhere"
    with pytest.raises(ItemWriteRefusedError) as unspent:
        rig.writer.read_draft(HUB, "agent-spt008")
    assert unspent.value.code == "link_in_path"
    before = _pages(rig)

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "agent-spt008", SCOUT_REF, confirm_managed=False)

    _assert_spent(rig, refused, before)
    assert rig.hub.skill_files[SCOUT] == _named("scout", "New.\n")
    assert rig.drafts() == [".hub-drafts/agent-spt008/scout.md"]


def _versions(rig: _Rig, *unit_paths: str) -> list[list[str]]:
    return [[version.id for version in rig.store.page(PROJECT, path)] for path in unit_paths]


def test_refuses_rename_retry_when_written_not_recorded() -> None:
    store = _PublishFailingStore()
    rig = _Rig({f"{ALPHA}/SKILL.md": _named("alpha")}, store=store)
    rig.draft("skill-unr001", {"SKILL.md": _named("alpha2")})
    alpha = _ref(ItemKind.SKILL, "demo", "alpha")
    with pytest.raises(ItemWrittenUnrecordedError):
        rig.publish.publish(PROJECT, "skill-unr001", alpha, confirm_managed=False)
    store.failing = False
    rig.writer.writes.clear()
    before = _versions(rig, ALPHA, RENAMED)

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, "skill-unr001", alpha, confirm_managed=False)

    assert refused.value.code == "item_exists"
    assert rig.writer.writes == []
    assert _versions(rig, ALPHA, RENAMED) == before
    assert rig.hub.skill_files[f"{ALPHA}/SKILL.md"] == _named("alpha")
    assert rig.drafts() == [".hub-drafts/skill-unr001/SKILL.md"]


@pytest.mark.parametrize(
    ("draft_id", "files", "unit"),
    [
        ("skill-unr002", {"SKILL.md": _named("changelog")}, "plugin/demo/skills/changelog"),
        ("agent-unr003", {"planner.md": _named("planner")}, "plugin/demo/agents/planner.md"),
    ],
)
def test_refuses_new_item_retry_when_written_not_recorded(
    draft_id: str, files: dict[str, bytes], unit: str
) -> None:
    store = _PublishFailingStore()
    rig = _Rig({}, store=store)
    rig.draft(draft_id, files)
    with pytest.raises(ItemWrittenUnrecordedError):
        rig.publish.publish(PROJECT, draft_id, None, confirm_managed=False)
    store.failing = False
    rig.writer.writes.clear()

    with pytest.raises(ItemWriteRefusedError) as refused:
        rig.publish.publish(PROJECT, draft_id, None, confirm_managed=False)

    assert refused.value.code == "item_exists"
    assert rig.writer.writes == []
    assert rig.store.page(PROJECT, unit) == ()
    assert rig.drafts() == sorted(f".hub-drafts/{draft_id}/{path}" for path in files)
