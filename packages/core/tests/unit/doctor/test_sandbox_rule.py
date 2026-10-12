"""``sandbox.workflow`` (AGH-134): the hub's own commands work inside the sandbox it turns on."""

from collections.abc import Callable
from dataclasses import replace

import pytest

from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.sandbox_rule import SANDBOX_WORKFLOW
from agent_hub.core.doctor.snapshot import DoctorSnapshot, RemoteProbe
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, Severity
from agent_hub.core.hub_files.sandbox_settings import WORKFLOW_EXCLUDED_COMMANDS
from agent_hub.core.hub_files.tree_snapshot import FolderEntry
from agent_hub.core.json_form import JsonValue, dump_json

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[Severity, str | None, str, str]

SETTINGS = ".claude/settings.json"
# The commands the template excludes, written out so a change to the list fails here.
WORKFLOW = (
    "gh *",
    "git push *",
    "git fetch *",
    "git pull *",
    "git clone *",
    "git ls-remote *",
    "./hub worktree *",
    "hub worktree *",
    "make worktree *",
    "make worktree-remove *",
)
OFF = (
    Severity.INFO,
    SETTINGS,
    "sandbox.enabled is not true: the sandbox is off, nothing to check",
    "none needed; hub sync's base settings turn the sandbox on",
)


def settings_with(sandbox: JsonValue) -> bytes:
    return dump_json({"$schema": "https://example.invalid/settings.json", "sandbox": sandbox})


def on_with(excluded: JsonValue) -> bytes:
    return settings_with({"enabled": True, "excludedCommands": excluded})


def missing(commands: str) -> Shown:
    return (
        Severity.ERROR,
        SETTINGS,
        f"sandbox.excludedCommands lacks {commands}: inside the sandbox the hub's own fetch,"
        " push, gh and worktree commands fail",
        "run hub sync",
    )


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(SANDBOX_WORKFLOW.check(snapshot))
    assert all(finding.rule == "sandbox.workflow" for finding in found)
    assert all(finding.line is None for finding in found)
    return [(finding.severity, finding.path, finding.message, finding.fix) for finding in found]


def test_declares_design_fields_when_rule_read() -> None:
    assert SANDBOX_WORKFLOW.id == "sandbox.workflow"
    assert SANDBOX_WORKFLOW.severity is Severity.ERROR
    assert SANDBOX_WORKFLOW.reads == frozenset({Read.REMOTES})
    assert SANDBOX_WORKFLOW.module is None
    assert RULE_IDS[-1] == "sandbox.workflow"
    assert WORKFLOW_EXCLUDED_COMMANDS == WORKFLOW


def test_reports_nothing_when_settings_exclude_workflow(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(files={SETTINGS: on_with(["docker *", *WORKFLOW, "npm *"])})

    assert findings_of(snapshot) == []


@pytest.mark.parametrize(
    "sandbox",
    [{"enabled": False}, {}, {"enabled": "true"}, None, []],
    ids=["false", "absent", "string", "null", "array"],
)
def test_reports_info_when_sandbox_off(snapshot_of: SnapshotFactory, sandbox: JsonValue) -> None:
    content = settings_with(sandbox)

    assert findings_of(snapshot_of(files={SETTINGS: content})) == [OFF]


def test_reports_info_when_settings_hold_no_sandbox(snapshot_of: SnapshotFactory) -> None:
    content = dump_json({"$schema": "https://example.invalid/settings.json"})

    assert findings_of(snapshot_of(files={SETTINGS: content})) == [OFF]


def test_names_each_missing_command_when_v090_settings(snapshot_of: SnapshotFactory) -> None:
    # The v0.9.0 template's list: the worktree spellings were not there.
    old = ["docker *", *WORKFLOW[:6]]

    found = findings_of(snapshot_of(files={SETTINGS: on_with(old)}))

    assert found == [
        missing("./hub worktree *, hub worktree *, make worktree *, make worktree-remove *")
    ]


@pytest.mark.parametrize("excluded", [None, "gh *", {"gh *": True}], ids=["null", "str", "obj"])
def test_names_every_command_when_list_not_array(
    snapshot_of: SnapshotFactory, excluded: JsonValue
) -> None:
    found = findings_of(snapshot_of(files={SETTINGS: on_with(excluded)}))

    assert found == [missing(", ".join(WORKFLOW))]


def test_reports_nothing_when_settings_missing_or_unreadable(
    snapshot_of: SnapshotFactory,
) -> None:
    # settings.weakening reports a missing, non-regular or invalid settings.json.
    for files, entries in (
        ({}, {}),
        ({SETTINGS: b"{not json"}, {}),
        ({SETTINGS: b"[]"}, {}),
        ({}, {SETTINGS: FolderEntry()}),
    ):
        assert findings_of(snapshot_of(files=files, entries=entries)) == []


def test_warns_each_unreachable_remote_when_probed(snapshot_of: SnapshotFactory) -> None:
    snapshot = replace(
        snapshot_of(files={SETTINGS: on_with(list(WORKFLOW))}),
        remote_probes=(
            RemoteProbe(dir="demo-api", problem=None),
            RemoteProbe(
                dir="demo-web",
                problem="ssh_dispatch_run_fatal: Connection to UNKNOWN port 65535: Broken pipe",
            ),
        ),
    )

    assert findings_of(snapshot) == [
        (
            Severity.WARNING,
            "../demo-web",
            "git ls-remote origin fails inside this sandboxed session"
            " (ssh_dispatch_run_fatal: Connection to UNKNOWN port 65535: Broken pipe); a hub"
            " worktree that runs sandboxed fails the same way",
            "run ./hub worktree <name> as a Bash call of its own (no cd &&, pipe or redirect),"
            " or a bare git fetch origin <branch> with ../demo-web as the cwd, then"
            " ./hub worktree --no-fetch <name>",
        )
    ]


def test_ignores_probes_when_sandbox_off(snapshot_of: SnapshotFactory) -> None:
    snapshot = replace(
        snapshot_of(files={SETTINGS: settings_with({"enabled": False})}),
        remote_probes=(RemoteProbe(dir="demo-api", problem="Broken pipe"),),
    )

    assert findings_of(snapshot) == [OFF]
