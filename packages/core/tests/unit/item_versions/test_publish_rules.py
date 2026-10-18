"""Publish rules (AGH-295, S5, D19, D24; AC-295.12, AC-295.13, AC-295.14, AC-295.15): a draft
read as an item, where an edit or a new item lands, one hook replaced in its file, new hooks
merged into the project plugin's file; replaying a publish gives the same bytes (A7)."""

import json

import pytest

from agent_hub.core.item_versions.hub_item_writer import ItemWriteRefusedError
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.publish_rules import (
    DraftInvalidError,
    DraftItem,
    HookAt,
    edit_destination,
    hook_at,
    merge_hooks,
    new_destination,
    read_draft_item,
    replace_hook,
)
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.json_form import JsonValue, dump_json
from agent_hub.core.readmodels.read_ports import EntityNotFoundError

PROJECT = "demo"
SKILL_UNIT = "plugin/demo/skills/alpha"
AGENT_UNIT = ".claude/agents/reviewer.md"


def _files(files: dict[str, bytes], *, executable: frozenset[str] = frozenset()) -> UnitContent:
    return UnitContent(
        files=tuple(
            UnitFile(path=path, content=content, executable=path in executable)
            for path, content in sorted(files.items())
        )
    )


def _named(name: str, body: str = "# Body\n") -> bytes:
    return f"---\nname: {name}\ndescription: Does a thing.\n---\n{body}".encode()


def _hooks(event: str, command: str, matcher: str | None = None) -> bytes:
    group: dict[str, JsonValue] = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        group["matcher"] = matcher
    return json.dumps({"hooks": {event: [group]}}).encode()


def _unit(path: str, kind: UnitKind) -> ItemUnit:
    return ItemUnit(project=PROJECT, unit_path=path, kind=kind)


def _paths(content: UnitContent) -> dict[str, bytes]:
    return {file.path: file.content for file in content.files}


def test_refuses_draft_when_name_invalid() -> None:
    drafts = {
        UnitKind.SKILL: [
            {"SKILL.md": _named("bad name")},
            {"SKILL.md": b"# no frontmatter\n"},
            {"SKILL.md": b"\xff\xfe not text"},
            {"SKILL.md": _named("x" * 129)},
        ],
        UnitKind.AGENT: [{"reviewer.md": _named("../up")}],
    }
    for kind, cases in drafts.items():
        for files in cases:
            with pytest.raises(DraftInvalidError) as refused:
                read_draft_item(kind, _files(files))
            assert refused.value.code == "draft_invalid"
            assert "/" not in refused.value.reason


def test_refuses_draft_when_main_file_missing_or_extra() -> None:
    cases = [
        (UnitKind.SKILL, {"references/r.md": b"# R\n"}),
        (UnitKind.AGENT, {"notes.txt": b"x"}),
        (UnitKind.AGENT, {"a.md": _named("a"), "b.md": _named("b")}),
        (UnitKind.AGENT, {"agents/a.md": _named("a")}),
        (UnitKind.HOOK, {"scripts/check.sh": b"#!/bin/sh\n"}),
        (UnitKind.HOOK, {"hooks.json": _hooks("Stop", "x"), "README.md": b"# R\n"}),
        (UnitKind.WORKFLOW, {"w.yaml": b"name: w\n"}),
    ]
    for kind, files in cases:
        with pytest.raises(DraftInvalidError):
            read_draft_item(kind, _files(files))


def test_refuses_draft_when_hidden_or_nested_name() -> None:
    hook = _hooks("PreToolUse", "${CLAUDE_PLUGIN_ROOT}/scripts/check.sh", "Bash")
    cases = [
        (UnitKind.HOOK, {"hooks.json": hook, "scripts/.x": b"x"}),
        (UnitKind.HOOK, {"hooks.json": hook, "scripts/a/b.sh": b"x"}),
        (UnitKind.SKILL, {"SKILL.md": _named("alpha"), ".cache/data": b"x"}),
        (UnitKind.SKILL, {"SKILL.md": _named("alpha"), "notes/.draft": b"x"}),
        (UnitKind.SKILL, {"SKILL.md": _named("alpha"), "refs": b"x", "refs/r.md": b"x"}),
    ]
    for kind, files in cases:
        with pytest.raises(DraftInvalidError):
            read_draft_item(kind, _files(files))


def test_refuses_draft_when_hooks_not_a_hooks_object() -> None:
    cases = [
        b"not json",
        b"[]",
        b'{"hooks": []}',
        b'{"hooks": {}}',
        b'{"hooks": {"Stop": [{"matcher": "x"}]}}',
        b'{"hooks": {"Stop": [{"hooks": ["not an object"]}]}}',
        b'{"hooks": {"bad event!": [{"hooks": [{"type": "command"}]}]}}',
    ]
    for content in cases:
        with pytest.raises(DraftInvalidError):
            read_draft_item(UnitKind.HOOK, _files({"hooks.json": content}))


def test_reads_hooks_and_scripts_when_hook_draft_valid() -> None:
    hook = _hooks("PreToolUse", "${CLAUDE_PLUGIN_ROOT}/scripts/check.sh", "Bash")
    files = _files(
        {"hooks.json": hook, "scripts/check.sh": b"#!/bin/sh\n"},
        executable=frozenset({"scripts/check.sh"}),
    )

    draft = read_draft_item(UnitKind.HOOK, files)

    assert draft.name is None
    assert draft.hooks == json.loads(hook)["hooks"]
    assert [file.path for file in draft.scripts] == ["scripts/check.sh"]


def test_keeps_files_draft_lacks_when_skill_edited() -> None:
    current = _files(
        {
            "SKILL.md": _named("alpha"),
            "references/r.md": b"# R\n",
            "references/keep.md": b"# Keep\n",
        }
    )
    draft = read_draft_item(
        UnitKind.SKILL,
        _files(
            {"SKILL.md": _named("alpha", "# Changed\n"), "scripts/s.sh": b"#!/bin/sh\n"},
            executable=frozenset({"scripts/s.sh"}),
        ),
    )

    destination = edit_destination(_unit(SKILL_UNIT, UnitKind.SKILL), current, draft, existing=())

    assert destination.unit == _unit(SKILL_UNIT, UnitKind.SKILL)
    assert destination.removed is None
    assert _paths(destination.content) == {
        "SKILL.md": _named("alpha", "# Changed\n"),
        "references/keep.md": b"# Keep\n",
        "references/r.md": b"# R\n",
        "scripts/s.sh": b"#!/bin/sh\n",
    }
    executable = {file.path for file in destination.content.files if file.executable}
    assert executable == {"scripts/s.sh"}


def test_moves_folder_when_skill_renamed() -> None:
    current = _files({"SKILL.md": _named("alpha"), "references/r.md": b"# R\n"})
    draft = read_draft_item(UnitKind.SKILL, _files({"SKILL.md": _named("alpha2")}))

    destination = edit_destination(_unit(SKILL_UNIT, UnitKind.SKILL), current, draft, existing=())

    assert destination.unit == _unit("plugin/demo/skills/alpha2", UnitKind.SKILL)
    assert destination.removed == _unit(SKILL_UNIT, UnitKind.SKILL)
    assert _paths(destination.content) == {
        "SKILL.md": _named("alpha2"),
        "references/r.md": b"# R\n",
    }


def test_renames_agent_file_when_name_changed() -> None:
    current = _files({"reviewer.md": _named("reviewer")})
    same = read_draft_item(UnitKind.AGENT, _files({"reviewer.md": _named("reviewer", "# New\n")}))
    renamed = read_draft_item(UnitKind.AGENT, _files({"reviewer.md": _named("critic")}))

    kept = edit_destination(_unit(AGENT_UNIT, UnitKind.AGENT), current, same, existing=())
    moved = edit_destination(_unit(AGENT_UNIT, UnitKind.AGENT), current, renamed, existing=())

    assert kept.unit == _unit(AGENT_UNIT, UnitKind.AGENT)
    assert kept.removed is None
    assert _paths(kept.content) == {"reviewer.md": _named("reviewer", "# New\n")}
    assert moved.unit == _unit(".claude/agents/critic.md", UnitKind.AGENT)
    assert moved.removed == _unit(AGENT_UNIT, UnitKind.AGENT)
    assert _paths(moved.content) == {"critic.md": _named("critic")}


def test_refuses_edit_when_draft_kind_differs_from_target() -> None:
    draft = read_draft_item(UnitKind.AGENT, _files({"reviewer.md": _named("reviewer")}))
    hook = read_draft_item(UnitKind.HOOK, _files({"hooks.json": _hooks("Stop", "x")}))
    current = _files({"SKILL.md": _named("alpha")})

    with pytest.raises(DraftInvalidError):
        edit_destination(_unit(SKILL_UNIT, UnitKind.SKILL), current, draft, existing=())
    with pytest.raises(ValueError, match="replace_hook"):
        edit_destination(_unit(".claude/settings.json", UnitKind.HOOK), current, hook, existing=())


def test_replaces_only_that_hook_when_hook_edited() -> None:
    settings: dict[str, JsonValue] = {
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "one"}]},
                {
                    "matcher": "Edit",
                    "hooks": [
                        {"type": "command", "command": "two"},
                        {"type": "command", "command": "three"},
                    ],
                },
            ],
            "Stop": [{"hooks": [{"type": "command", "command": "stop"}]}],
        },
    }
    draft = read_draft_item(
        UnitKind.HOOK, _files({"hooks.json": _hooks("PreToolUse", "2", "Edit")})
    )
    assert draft.hooks is not None

    at = hook_at(source="settings", name="settings-pretooluse-2", event="PreToolUse")
    written = replace_hook(json.dumps(settings).encode(), at, draft.hooks)

    expected = json.loads(json.dumps(settings))
    expected["hooks"]["PreToolUse"][1]["hooks"][0]["command"] = "2"
    assert written == dump_json(expected)


def test_moves_hook_when_draft_changes_its_event_or_matcher() -> None:
    settings = {
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "one"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "stop"}]}],
        }
    }
    draft = read_draft_item(UnitKind.HOOK, _files({"hooks.json": _hooks("Stop", "moved")}))
    assert draft.hooks is not None

    written = replace_hook(json.dumps(settings).encode(), HookAt("PreToolUse", 1), draft.hooks)

    assert json.loads(written) == {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "stop"}]},
                {"hooks": [{"type": "command", "command": "moved"}]},
            ]
        }
    }


def test_answers_not_found_when_hook_not_in_file() -> None:
    settings = _hooks("Stop", "stop")
    new_hooks: dict[str, JsonValue] = {"Stop": [{"hooks": [{"type": "command"}]}]}

    for at in (HookAt("Stop", 2), HookAt("PreToolUse", 1)):
        with pytest.raises(EntityNotFoundError):
            replace_hook(settings, at, new_hooks)
    with pytest.raises(ItemWriteRefusedError) as refused:
        replace_hook(b'{"hooks": []}', HookAt("Stop", 1), new_hooks)
    assert refused.value.code == "unit_unreadable"


def test_locates_hook_when_name_has_case_suffix() -> None:
    assert hook_at(source="tools", name="tools-stop-3-2", event="Stop") == HookAt("Stop", 3)
    with pytest.raises(ValueError, match="hook name"):
        hook_at(source="tools", name="other-stop-1", event="Stop")


def test_merges_hooks_when_new_hook_published() -> None:
    hook = _hooks("PreToolUse", "${CLAUDE_PLUGIN_ROOT}/scripts/check.sh", "Bash")
    draft = read_draft_item(
        UnitKind.HOOK,
        _files(
            {"hooks.json": hook, "scripts/check.sh": b"#!/bin/sh\n"},
            executable=frozenset({"scripts/check.sh"}),
        ),
    )
    existing = _hooks("PreToolUse", "old", "Edit")

    created = new_destination(PROJECT, draft, current_hooks=None)
    merged = new_destination(PROJECT, draft, current_hooks=existing)

    assert created.unit == _unit("plugin/demo/hooks/hooks.json", UnitKind.HOOK)
    assert _paths(created.content) == {"hooks.json": dump_json(json.loads(hook))}
    assert json.loads(_paths(merged.content)["hooks.json"]) == {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Edit", "hooks": [{"type": "command", "command": "old"}]},
                json.loads(hook)["hooks"]["PreToolUse"][0],
            ]
        }
    }
    assert [(file.path, file.executable) for file in merged.scripts] == [
        ("plugin/demo/scripts/check.sh", True)
    ]
    assert merged.removed is None


def test_refuses_merge_when_hooks_file_not_a_hooks_object() -> None:
    new_hooks: dict[str, JsonValue] = {"Stop": [{"hooks": [{"type": "command"}]}]}

    for current in (b"not json", b"[]", b'{"hooks": []}', b'{"hooks": {"Stop": {}}}'):
        with pytest.raises(ItemWriteRefusedError) as refused:
            merge_hooks(current, new_hooks)
        assert refused.value.code == "unit_unreadable"


def test_places_new_skill_in_project_plugin_when_target_null() -> None:
    skill = read_draft_item(
        UnitKind.SKILL, _files({"SKILL.md": _named("changelog"), "references/r.md": b"# R\n"})
    )
    agent = read_draft_item(UnitKind.AGENT, _files({"draft.md": _named("planner")}))

    placed = new_destination(PROJECT, skill)
    placed_agent = new_destination(PROJECT, agent)

    assert placed.unit == _unit("plugin/demo/skills/changelog", UnitKind.SKILL)
    assert placed.content == skill.content
    assert placed.removed is None
    assert placed.scripts == ()
    assert placed_agent.unit == _unit("plugin/demo/agents/planner.md", UnitKind.AGENT)
    assert _paths(placed_agent.content) == {"planner.md": _named("planner")}
    assert isinstance(skill, DraftItem)


_NOT_STRICT = (
    b'{"hooks": {"Stop": [{"hooks": [{"type": "command", "timeout": NaN}]}]}}',
    b'{"hooks": {"Stop": [{"hooks": [{"type": "command", "timeout": 1e999}]}]}}',
    b'{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "\\ud800"}]}]}}',
    b'{"hooks": {"Stop": [{"hooks": [{"type": "command"}]}]}, "hooks": {}}',
)


def test_refuses_draft_when_hooks_json_not_strict_json() -> None:
    for content in _NOT_STRICT:
        with pytest.raises(DraftInvalidError):
            read_draft_item(UnitKind.HOOK, _files({"hooks.json": content}))


def test_refuses_hook_file_when_on_disk_not_strict_json() -> None:
    new_hooks: dict[str, JsonValue] = {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}

    for content in _NOT_STRICT:
        for write in (
            lambda file: merge_hooks(file, new_hooks),
            lambda file: replace_hook(file, HookAt("Stop", 1), new_hooks),
        ):
            with pytest.raises(ItemWriteRefusedError) as refused:
                write(content)
            assert refused.value.code == "unit_unreadable"


def test_gives_same_bytes_when_merge_run_twice() -> None:
    draft = read_draft_item(UnitKind.HOOK, _files({"hooks.json": _hooks("Stop", "new", "x")}))
    assert draft.hooks is not None

    for current in (None, _hooks("Stop", "old")):
        once = merge_hooks(current, draft.hooks)
        assert merge_hooks(once, draft.hooks) == once
    assert len(json.loads(once)["hooks"]["Stop"]) == 2


def test_gives_same_bytes_when_replace_run_twice() -> None:
    settings = json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "one"}]},
                    {"matcher": "Edit", "hooks": [{"type": "command", "command": "two"}]},
                ],
                "Stop": [{"hooks": [{"type": "command", "command": "stop"}]}],
            }
        }
    ).encode()
    drafts = (_hooks("PreToolUse", "changed", "Bash"), _hooks("Stop", "moved"))

    for content in drafts:
        draft = read_draft_item(UnitKind.HOOK, _files({"hooks.json": content}))
        assert draft.hooks is not None
        once = replace_hook(settings, HookAt("PreToolUse", 1), draft.hooks)
        assert replace_hook(once, HookAt("PreToolUse", 1), draft.hooks) == once
        assert once != dump_json(json.loads(settings))


def test_keeps_emptied_group_when_it_holds_other_keys() -> None:
    settings = json.dumps(
        {"hooks": {"Stop": [{"note": "kept", "hooks": [{"type": "command", "command": "a"}]}]}}
    ).encode()
    draft = read_draft_item(UnitKind.HOOK, _files({"hooks.json": _hooks("Stop", "b", "x")}))
    assert draft.hooks is not None

    written = replace_hook(settings, HookAt("Stop", 1), draft.hooks)

    assert json.loads(written) == {
        "hooks": {
            "Stop": [
                {"note": "kept", "hooks": []},
                {"matcher": "x", "hooks": [{"type": "command", "command": "b"}]},
            ]
        }
    }


def test_refuses_rename_when_only_case_changes() -> None:
    cases = [
        (SKILL_UNIT, UnitKind.SKILL, {"SKILL.md": _named("Alpha")}, {"SKILL.md": _named("alpha")}),
        (AGENT_UNIT, UnitKind.AGENT, {"x.md": _named("Reviewer")}, {"reviewer.md": b"x"}),
    ]
    for unit_path, kind, files, current in cases:
        draft = read_draft_item(kind, _files(files))
        with pytest.raises(DraftInvalidError):
            edit_destination(_unit(unit_path, kind), _files(current), draft, existing=())


def test_refuses_rename_when_sibling_unit_exists() -> None:
    skill = read_draft_item(UnitKind.SKILL, _files({"SKILL.md": _named("beta")}))
    agent = read_draft_item(UnitKind.AGENT, _files({"x.md": _named("critic")}))
    cases = [
        (SKILL_UNIT, skill, ["plugin/demo/skills/Beta"]),
        (AGENT_UNIT, agent, [".claude/agents/critic.md"]),
    ]
    for unit_path, draft, existing in cases:
        with pytest.raises(ItemWriteRefusedError) as refused:
            edit_destination(_unit(unit_path, draft.kind), _files({}), draft, existing=existing)
        assert refused.value.code == "item_exists"
    elsewhere = edit_destination(
        _unit(SKILL_UNIT, UnitKind.SKILL),
        _files({"SKILL.md": _named("alpha")}),
        skill,
        existing=[".claude/skills/beta", SKILL_UNIT],
    )
    assert elsewhere.unit.unit_path == "plugin/demo/skills/beta"
