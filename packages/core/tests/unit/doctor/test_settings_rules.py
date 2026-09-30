from collections.abc import Callable

import pytest

from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.settings_rules import SETTINGS_WEAKENING, _group_key
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, LinkEntry, TreeEntry
from agent_hub.core.json_form import JsonValue, dump_json, load_json_bytes

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[Severity, str | None, str, str]

SETTINGS = ".claude/settings.json"
PROJECT = ".claude/settings.project.json"
SYNC_FIX = "run hub sync"
PROJECT_FIX = "fix or delete it: hub sync cannot merge it either"
REFUSED = "refused: a project cannot set this key (it weakens the harness)"
CHANGED = "a base hook group is missing or changed"
# Deep enough that the indented byte form is huge (its size grows with the depth squared).
DEEP = 20_000


def a_group(command: str, *, timeout: JsonValue, matcher: str | None = None) -> JsonValue:
    hook: JsonValue = {"type": "command", "command": command, "timeout": timeout}
    if matcher is None:
        return {"hooks": [hook]}
    return {"matcher": matcher, "hooks": [hook]}


def base_block() -> dict[str, JsonValue]:
    """A synthetic base hooks block: a group with a matcher and one without."""
    return {
        "SessionStart": [a_group("python3 start.py", timeout=20, matcher="startup")],
        "Stop": [a_group("python3 stop.py", timeout=180)],
    }


def settings_with(hooks: JsonValue) -> bytes:
    return dump_json({"$schema": "https://example.invalid/settings.json", "hooks": hooks})


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(SETTINGS_WEAKENING.check(snapshot))
    assert all(finding.rule == "settings.weakening" for finding in found)
    assert all(finding.line is None for finding in found)
    return [(finding.severity, finding.path, finding.message, finding.fix) for finding in found]


def hub_of(snapshot_of: SnapshotFactory, **changes: object) -> DoctorSnapshot:
    """A hub whose ``settings.json`` holds the base block, with ``changes`` applied."""
    arguments: dict[str, object] = {
        "files": {SETTINGS: settings_with(base_block())},
        "base_hooks": base_block(),
    }
    return snapshot_of(**(arguments | changes))


def test_reports_nothing_when_settings_keep_base_hooks(snapshot_of: SnapshotFactory) -> None:
    project = dump_json({"permissions": {"allow": ["Bash(make check)"]}, "env": {"A": "1"}})

    assert findings_of(hub_of(snapshot_of)) == []
    snapshot = hub_of(snapshot_of, files={SETTINGS: settings_with(base_block()), PROJECT: project})
    assert findings_of(snapshot) == []


def test_reads_base_hooks_when_rule_declared() -> None:
    assert SETTINGS_WEAKENING.reads == frozenset({Read.BASE_HOOKS})
    assert SETTINGS_WEAKENING.severity is Severity.ERROR


@pytest.mark.parametrize(
    ("project", "keys"),
    [
        pytest.param({"disableAllHooks": False}, ["disableAllHooks"], id="disable-all-false"),
        pytest.param(
            {"permissions": {"allow": [], "defaultMode": "acceptEdits"}},
            ["permissions.defaultMode"],
            id="default-mode",
        ),
        pytest.param(
            {"permissions": {"defaultMode": "plan"}, "disableAllHooks": True},
            ["disableAllHooks", "permissions.defaultMode"],
            id="both",
        ),
    ],
)
def test_reports_each_refused_key_when_project_settings_weaken(
    snapshot_of: SnapshotFactory, *, project: JsonValue, keys: list[str]
) -> None:
    files = {SETTINGS: settings_with(base_block()), PROJECT: dump_json(project)}

    assert findings_of(hub_of(snapshot_of, files=files)) == [
        (Severity.ERROR, PROJECT, f"{key}: {REFUSED}", f"remove {key} from {PROJECT}")
        for key in keys
    ]


def test_ignores_key_when_refused_name_nested_elsewhere(snapshot_of: SnapshotFactory) -> None:
    project = dump_json({"env": {"disableAllHooks": "1", "defaultMode": "plan"}, "permissions": []})
    files = {SETTINGS: settings_with(base_block()), PROJECT: project}

    assert findings_of(hub_of(snapshot_of, files=files)) == []


def test_reports_refused_key_when_settings_hold_it(snapshot_of: SnapshotFactory) -> None:
    # A synced settings.json never holds one: it was written there by hand.
    settings = dump_json({"disableAllHooks": False, "hooks": base_block()})

    assert findings_of(hub_of(snapshot_of, files={SETTINGS: settings})) == [
        (Severity.ERROR, SETTINGS, f"disableAllHooks: {REFUSED}", SYNC_FIX)
    ]


def _without_stop_group() -> JsonValue:
    return base_block() | {"Stop": []}


def _without_stop_event() -> JsonValue:
    block = base_block()
    del block["Stop"]
    return block


def _retimed_session_start() -> JsonValue:
    return base_block() | {
        "SessionStart": [a_group("python3 start.py", timeout=21, matcher="startup")]
    }


def _session_start_not_a_list() -> JsonValue:
    return base_block() | {"SessionStart": a_group("python3 start.py", timeout=20)}


@pytest.mark.parametrize(
    ("hooks", "events"),
    [
        pytest.param(_without_stop_group(), ["Stop"], id="group-removed"),
        pytest.param(_without_stop_event(), ["Stop"], id="event-removed"),
        pytest.param(_retimed_session_start(), ["SessionStart"], id="timeout-changed"),
        pytest.param(_session_start_not_a_list(), ["SessionStart"], id="event-not-array"),
        pytest.param([], ["SessionStart", "Stop"], id="hooks-not-object"),
    ],
)
def test_reports_event_when_base_hook_group_missing_or_retimed(
    snapshot_of: SnapshotFactory, *, hooks: JsonValue, events: list[str]
) -> None:
    snapshot = hub_of(snapshot_of, files={SETTINGS: settings_with(hooks)})

    assert findings_of(snapshot) == [
        (Severity.ERROR, SETTINGS, f"hooks.{event}: {CHANGED}", SYNC_FIX) for event in events
    ]


def test_reports_every_event_when_settings_not_object(snapshot_of: SnapshotFactory) -> None:
    snapshot = hub_of(snapshot_of, files={SETTINGS: dump_json([base_block()])})

    assert [finding[2] for finding in findings_of(snapshot)] == [
        f"hooks.SessionStart: {CHANGED}",
        f"hooks.Stop: {CHANGED}",
    ]


def _with_own_groups() -> JsonValue:
    """The base block with a project group before the base one and a project event."""
    return base_block() | {
        "Stop": [a_group("python3 own.py", timeout=5), a_group("python3 stop.py", timeout=180)],
        "PostToolUse": [a_group("python3 own.py", timeout=5, matcher="Edit")],
    }


@pytest.mark.parametrize(
    "settings",
    [
        pytest.param(settings_with(_with_own_groups()), id="group-and-event"),
    ],
)
def test_accepts_project_hook_group_when_added_beside_base(
    snapshot_of: SnapshotFactory, settings: bytes
) -> None:
    assert findings_of(hub_of(snapshot_of, files={SETTINGS: settings})) == []


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        pytest.param({}, "missing; hub sync restores it", id="absent"),
        pytest.param(
            {SETTINGS: FileEntry(executable=False, content=b'{"hooks": \n')},
            "$: not valid JSON: Expecting value at line 2 column 1",
            id="invalid-json",
        ),
        pytest.param(
            {SETTINGS: FileEntry(executable=False, content=b"\xef\xbb\xbf{}")},
            "$: not valid JSON: the file starts with a UTF-8 byte order mark; save it without one",
            id="byte-order-mark",
        ),
        pytest.param(
            {SETTINGS: LinkEntry(target="settings.real.json", outside=False)},
            "not a regular file",
            id="link",
        ),
        pytest.param({SETTINGS: FolderEntry()}, "not a regular file", id="folder"),
        pytest.param(
            {
                SETTINGS: FileEntry(
                    executable=False,
                    content=settings_with(base_block()).replace(
                        b'"Stop": [', b'"Stop": [{"hooks": [], "timeout": NaN}, '
                    ),
                )
            },
            "$: not valid JSON here: NaN is not a JSON number",
            id="nan-beside-base",
        ),
        pytest.param(
            {
                SETTINGS: FileEntry(
                    executable=False,
                    content=settings_with(base_block()).replace(b"{\n", b'{\n  "hooks": {},\n', 1),
                )
            },
            '$: not valid JSON here: the key "hooks" appears more than once',
            id="repeated-key",
        ),
    ],
)
def test_reports_error_when_settings_absent_or_invalid(
    snapshot_of: SnapshotFactory, *, entries: dict[str, TreeEntry], message: str
) -> None:
    snapshot = hub_of(snapshot_of, files={}, entries=entries)

    assert findings_of(snapshot) == [(Severity.ERROR, SETTINGS, message, SYNC_FIX)]


def test_skips_absent_settings_when_hub_files_not_all_read(snapshot_of: SnapshotFactory) -> None:
    # The read may have failed on it: the runner reports that failure instead.
    snapshot = hub_of(snapshot_of, files={}, problem="could not read the files: .claude: denied")

    assert findings_of(snapshot) == []


def test_reports_missing_settings_when_only_listing_failed(snapshot_of: SnapshotFactory) -> None:
    snapshot = hub_of(
        snapshot_of,
        files={},
        problem="could not list the files: git not found",
        paths_read=True,
    )

    assert findings_of(snapshot) == [
        (Severity.ERROR, SETTINGS, "missing; hub sync restores it", SYNC_FIX)
    ]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        pytest.param(
            FileEntry(executable=False, content=b'{"env": {\n'),
            "$: not valid JSON: Expecting property name enclosed in double quotes"
            " at line 2 column 1",
            id="invalid-json",
        ),
        pytest.param(
            FileEntry(executable=False, content=b'{"env": {}, "env": {}}'),
            '$: not valid JSON here: the key "env" appears more than once',
            id="repeated-key",
        ),
        pytest.param(
            LinkEntry(target="elsewhere.json", outside=False), "not a regular file", id="link"
        ),
    ],
)
def test_reports_error_when_project_settings_invalid(
    snapshot_of: SnapshotFactory, *, entry: TreeEntry, message: str
) -> None:
    snapshot = hub_of(snapshot_of, entries={PROJECT: entry})

    assert findings_of(snapshot) == [(Severity.ERROR, PROJECT, message, PROJECT_FIX)]


def test_compares_groups_by_json_form_when_values_equal_in_python(
    snapshot_of: SnapshotFactory,
) -> None:
    base = {"Stop": [a_group("python3 stop.py", timeout=1)]}
    held = {"Stop": [a_group("python3 stop.py", timeout=True)]}
    assert base == held

    snapshot = snapshot_of(files={SETTINGS: settings_with(held)}, base_hooks=base)

    assert findings_of(snapshot) == [(Severity.ERROR, SETTINGS, f"hooks.Stop: {CHANGED}", SYNC_FIX)]


def test_reports_nothing_when_base_hooks_not_read(snapshot_of: SnapshotFactory) -> None:
    project = dump_json({"disableAllHooks": False})

    assert findings_of(snapshot_of(files={PROJECT: project}, base_hooks=None)) == []


def test_compares_deep_group_by_linear_key_when_project_nests_it(
    snapshot_of: SnapshotFactory,
) -> None:
    deep = b"[" * DEEP + b"]" * DEEP
    settings = settings_with(base_block()).replace(b'"Stop": [', b'"Stop": [' + deep + b", ", 1)

    assert findings_of(hub_of(snapshot_of, files={SETTINGS: settings})) == []
    # The indented byte form of this group is quadratic (about 400 M characters); the key is not.
    assert len(_group_key(load_json_bytes(deep, strict=True))) <= 3 * DEEP
