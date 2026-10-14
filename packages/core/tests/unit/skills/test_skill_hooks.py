import json

import pytest

from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.skills.skill_hooks import HookRecord, hook_records, load_hub_json
from agent_hub.core.skills.skill_sources import MAX_HOOKS, MAX_SKILL_JSON_BYTES
from agent_hub.core.skills.skill_view import HookFacts, Origin


def _json(document: object) -> bytes:
    return json.dumps(document).encode()


def _group(*commands: str, matcher: str | None = None) -> dict[str, object]:
    group: dict[str, object] = {
        "hooks": [{"type": "command", "command": command} for command in commands]
    }
    if matcher is not None:
        group["matcher"] = matcher
    return group


def _settings(**events: list[dict[str, object]]) -> bytes:
    return _json({"hooks": events})


def _names(records: tuple[HookRecord, ...]) -> list[str]:
    return [record.name for record in records]


def test_names_hooks_when_settings_and_plugin_list_them() -> None:
    settings = _settings(
        PreToolUse=[_group("guard", matcher="Bash"), _group("sensor", matcher="*")],
        SessionStart=[_group("brief")],
    )
    hooks = _json({"hooks": {"Stop": [_group("stop-gate")]}})

    fold = hook_records(
        settings,
        None,
        {"hub-workflow": hooks},
        enabled={"hub-workflow@agent-hub": True},
        marketplace="agent-hub",
    )

    assert _names(fold.records) == [
        "settings-pretooluse-1",
        "settings-pretooluse-2",
        "settings-sessionstart-1",
        "hub-workflow-stop-1",
    ]
    first = fold.records[0]
    assert first.source == "settings"
    assert first.source_path == ".claude/settings.json"
    assert first.origin is Origin.MANAGED
    assert first.facts == HookFacts(
        event="PreToolUse",
        matcher="Bash",
        type="command",
        command="guard",
        timeout=None,
        active=True,
        state="synced",
    )
    plugin = fold.records[3]
    assert (plugin.source, plugin.source_path, plugin.origin, plugin.facts.active) == (
        "hub-workflow",
        "plugin/hub-workflow/hooks/hooks.json",
        Origin.MANAGED,
        True,
    )
    assert fold.notices == ()
    assert not fold.truncated


def test_marks_project_and_not_synced_when_settings_differ() -> None:
    settings = _settings(SessionStart=[_group("brief")], Stop=[_group("gate")])
    project = _settings(SessionStart=[_group("brief"), _group("project-only")])

    fold = hook_records(settings, project, {}, enabled={}, marketplace="agent-hub")

    by_name = {record.name: record for record in fold.records}
    assert list(by_name) == [
        "settings-sessionstart-1",
        "settings-stop-1",
        "settings-project-sessionstart-2",
    ]
    assert by_name["settings-sessionstart-1"].origin is Origin.PROJECT_OWNED
    assert by_name["settings-stop-1"].origin is Origin.MANAGED
    missing = by_name["settings-project-sessionstart-2"]
    assert missing.source == "settings-project"
    assert missing.source_path == ".claude/settings.project.json"
    assert missing.origin is Origin.PROJECT_OWNED
    assert missing.facts.state == "not synced"
    assert not missing.facts.active


def test_marks_inactive_when_plugin_disabled() -> None:
    hooks = _json({"hooks": {"Stop": [_group("stop-gate")]}})

    fold = hook_records(
        None,
        None,
        {"hub-workflow": hooks, "demo": hooks, "extra": hooks},
        enabled={"hub-workflow@agent-hub": False, "demo@agent-hub": True},
        marketplace="agent-hub",
    )

    active = {record.source: record.facts.active for record in fold.records}
    assert active == {"demo": True, "extra": False, "hub-workflow": False}
    assert {record.source: record.origin for record in fold.records}["demo"] is (
        Origin.PROJECT_OWNED
    )


def test_marks_inactive_when_marketplace_unknown() -> None:
    hooks = _json({"hooks": {"Stop": [_group("stop-gate")]}})

    fold = hook_records(None, None, {"demo": hooks}, enabled={"demo@x": True}, marketplace=None)

    assert [record.facts.active for record in fold.records] == [False]


def test_keeps_matcher_and_timeout_when_hook_sets_them() -> None:
    settings = _json(
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Edit|Write",
                        "hooks": [{"type": "command", "command": "lint", "timeout": 60}],
                    }
                ]
            }
        }
    )

    (record,) = hook_records(settings, None, {}, enabled={}, marketplace=None).records

    assert (record.facts.matcher, record.facts.timeout) == ("Edit|Write", 60)


MALFORMED = {
    "not json": b"{not json",
    "not an object": b"[1, 2]",
    "hooks not an object": _json({"hooks": []}),
    "hooks not a list": _json({"hooks": {"Stop": {"hooks": []}}}),
    "group without hooks": _json({"hooks": {"Stop": [{"matcher": "x"}]}}),
    "hook not an object": _json({"hooks": {"Stop": [{"hooks": ["cmd"]}]}}),
    "deep nesting": b"[" * 100_000 + b"]" * 100_000,
    "too large": b" " * (MAX_SKILL_JSON_BYTES + 1),
    "not read": UnreadHubFile(message="File is not a regular file", is_missing=False),
    "bad event name": _json({"hooks": {"Pre Tool/Use": [_group("x")]}}),
}


@pytest.mark.parametrize("content", MALFORMED.values(), ids=MALFORMED.keys())
def test_reports_notice_when_json_malformed(content: bytes | UnreadHubFile) -> None:
    fold = hook_records(content, None, {}, enabled={}, marketplace=None)

    (notice,) = fold.notices
    assert notice.startswith(".claude/settings.json: ")
    assert "\n" not in notice
    assert fold.records == ()


def test_keeps_good_hooks_when_one_entry_malformed() -> None:
    settings = _json({"hooks": {"Stop": [{"hooks": ["bad"]}, _group("good")]}})

    fold = hook_records(settings, None, {}, enabled={}, marketplace=None)

    assert _names(fold.records) == ["settings-stop-1"]
    assert len(fold.notices) == 1


def test_skips_event_when_name_ends_with_newline() -> None:
    settings = _json({"hooks": {"Stop\n": [_group("bad")], "Stop": [_group("good")]}})

    fold = hook_records(settings, None, {}, enabled={}, marketplace=None)

    assert _names(fold.records) == ["settings-stop-1"]
    assert fold.notices == (
        ".claude/settings.json: some hooks not read"
        " (an event name is not letters, digits, '-' or '_')",
    )


def test_keeps_ids_unique_when_events_differ_only_by_case() -> None:
    settings = _json(
        {
            "hooks": {
                "Stop": [_group("one", "two")],
                "stop": [_group("three")],
                "Stop-1": [_group("x", "four")],
            }
        }
    )

    fold = hook_records(settings, None, {}, enabled={}, marketplace=None)

    assert _names(fold.records) == [
        "settings-stop-1",
        "settings-stop-2",
        "settings-stop-1-2",
        "settings-stop-1-1",
        "settings-stop-1-2-2",
    ]
    assert [record.facts.command for record in fold.records] == [
        "one",
        "two",
        "three",
        "x",
        "four",
    ]
    assert fold.notices == (
        ".claude/settings.json: 2 hook names taken by another event (events differing only by"
        " case); a suffix keeps them apart",
    )


def test_reads_nothing_when_files_absent() -> None:
    missing = UnreadHubFile(message="File does not exist", is_missing=True)

    fold = hook_records(None, missing, {"demo": missing}, enabled={}, marketplace=None)

    assert (fold.records, fold.notices) == ((), ())


def test_truncates_when_hooks_over_cap() -> None:
    settings = _settings(Stop=[_group(*(f"c{n}" for n in range(MAX_HOOKS + 1)))])

    fold = hook_records(settings, None, {}, enabled={}, marketplace=None)

    assert len(fold.records) == MAX_HOOKS
    assert fold.truncated


def test_gives_object_when_hub_json_loaded() -> None:
    loaded = load_hub_json(".claude/settings.json", b'{"a": 1}')

    assert (loaded.document, loaded.notice) == ({"a": 1}, None)
