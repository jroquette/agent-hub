"""Publish a Studio draft (AGH-295, D10, D19, D21, D24, S4, S5, A2, A5, A7, A8; AC-295.11-16):
the hand edit is recorded first, the draft lands where the publish rules say under one lock, a
``publish`` version naming the draft is recorded, then the draft is removed; an equal draft or a
replay writes and records nothing and removes the draft."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

import pytest

from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.item_versions.hub_item_writer import ItemWriteRefusedError
from agent_hub.core.item_versions.item_version import VersionAuthor, VersionOrigin
from agent_hub.core.item_versions.item_version_ports import MarkedUnit, ToolkitRef
from agent_hub.core.item_versions.publish_draft import DraftNotRemovedError, PublishDraft
from agent_hub.core.item_versions.publish_rules import DraftInvalidError
from agent_hub.core.item_versions.record_and_write import RecordAndWrite
from agent_hub.core.item_versions.unit_hash import file_hash
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_reads import SkillReads
from agent_hub.core.skills.skill_view import ItemKind, SkillCatalog, SkillDetail
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader
from agent_hub.core.testing.item_version_fakes import FakeHubItemWriter, InMemoryItemVersionStore

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

    def project_hubs(self) -> Iterator[tuple[str, str]]:
        return iter([(PROJECT, HUB)])

    def skill_catalog(self, project: str) -> SkillCatalog:
        return self._reads.catalog(project=project, hub_path=HUB)

    def skill_detail(self, project: str, *, kind: ItemKind, source: str, name: str) -> SkillDetail:
        return self._reads.detail(
            project=project, hub_path=HUB, kind=kind, source=source, name=name
        )

    def marked_skill_unit(
        self, project: str, *, kind: ItemKind, source: str, name: str
    ) -> MarkedUnit | None:
        return self._reads.marked_unit(project, HUB, kind=kind, source=source, name=name)


class _Rig:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.hub = FakeHub(skill_files=dict(files))
        reader = FakeHubFileReader({HUB: self.hub})
        self.store = InMemoryItemVersionStore()
        self.capture = CaptureItemVersions(self.store, reader, lambda: NOW)
        self.writer = FakeHubItemWriter({HUB: self.hub})
        self.catalog = _Catalog(SkillReads(reader, capture=self.capture))
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
    rig.writer.fail_on.clear()

    again = rig.publish.publish(PROJECT, "agent-rm0001", SCOUT_REF, confirm_managed=False)

    assert not again.changed
    assert rig.origins(SCOUT) == [VersionOrigin.EXTERNAL, VersionOrigin.PUBLISH]
    assert rig.drafts() == []


def test_replays_moved_hook_when_draft_removal_failed() -> None:
    settings = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "one"}]},
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "two"}]},
            ],
        }
    }
    rig = _Rig({SETTINGS: json.dumps(settings).encode()})
    rig.draft("hook-mov001", {"hooks.json": _hooks("Stop", "moved")})
    rig.writer.fail_on.add(".hub-drafts/hook-mov001")
    ref = _ref(ItemKind.HOOK, "settings", "settings-pretooluse-1")

    with pytest.raises(DraftNotRemovedError):
        rig.publish.publish(PROJECT, "hook-mov001", ref, confirm_managed=False)
    once = rig.hub.skill_files[SETTINGS]
    rig.writer.fail_on.clear()
    again = rig.publish.publish(PROJECT, "hook-mov001", ref, confirm_managed=False)

    assert json.loads(once) == {
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "two"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "moved"}]}],
        }
    }
    assert rig.hub.skill_files[SETTINGS] == once
    assert not again.changed
    assert rig.drafts() == []


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


def test_finishes_new_item_when_retried_after_draft_not_removed() -> None:
    rig = _Rig({})
    rig.draft("agent-new003", {"planner.md": _named("planner")})
    rig.writer.fail_on.add(".hub-drafts/agent-new003")

    with pytest.raises(DraftNotRemovedError):
        rig.publish.publish(PROJECT, "agent-new003", None, confirm_managed=False)
    rig.writer.fail_on.clear()
    again = rig.publish.publish(PROJECT, "agent-new003", None, confirm_managed=False)

    assert not again.changed
    assert rig.origins("plugin/demo/agents/planner.md") == [VersionOrigin.PUBLISH]
    assert rig.drafts() == []
