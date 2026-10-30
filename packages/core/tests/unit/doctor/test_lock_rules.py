import hashlib
from collections.abc import Callable, Mapping
from dataclasses import replace

import pytest

from agent_hub.core.doctor.lock_rules import LOCK_DRIFT, lock_paths, lock_state
from agent_hub.core.doctor.snapshot import (
    DoctorSnapshot,
    LockAbsent,
    LockNotRegular,
    LockState,
    ReleaseFound,
    ReleaseProbe,
    ReleaseProbeFailed,
    ReleaseTagMissing,
)
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_files.hub_lock import (
    HubLock,
    LockEntry,
    ManagedFileEntry,
    ManagedLinkEntry,
    SeededEntry,
)
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, LinkEntry, OtherEntry

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[Severity, str | None, str, str]

# The builder's pin, so a lock of this release is neither older nor newer.
PIN = "0.2.0"
SYNC_FIX = "run hub sync"
LOCK_WAY_OUT = "restore it from git, or run hub sync --adopt"
MISSING = "missing; hub sync restores it"
SCRIPT = b"#!/bin/sh\necho demo\n"
SETTINGS = b"{}\n"


def managed_file(content: bytes, *, executable: bool = False) -> ManagedFileEntry:
    return ManagedFileEntry(
        ownership="managed", sha256=hashlib.sha256(content).hexdigest(), executable=executable
    )


def a_lock(
    files: Mapping[str, LockEntry], *, platform_version: str = PIN, **header: str
) -> HubLock:
    return HubLock(
        lock_version=1,
        platform_version=platform_version,
        schema_version=1,
        modules=(),
        files=dict(files),
        **header,
    )


# A managed file, a managed executable file, a managed link and a seeded file.
LOCK = a_lock(
    {
        ".claude/settings.json": managed_file(SETTINGS),
        "scripts/run.sh": managed_file(SCRIPT, executable=True),
        ".claude/agents/lead.md": ManagedLinkEntry(
            ownership="managed", symlink="../../plugin/hub-workflow/agents/lead.md"
        ),
        "AGENTS.md": SeededEntry(ownership="seeded"),
        "hub.json": SeededEntry(ownership="seeded"),
    }
)
LINK_TARGET = "../../plugin/hub-workflow/agents/lead.md"


def hub_as_locked(snapshot_of: SnapshotFactory, **changes: object) -> DoctorSnapshot:
    """The hub ``LOCK`` records, every managed path as locked, with ``changes`` applied."""
    arguments: dict[str, object] = {
        "files": {".claude/settings.json": SETTINGS, "AGENTS.md": b"# Agents\n"},
        "links": {".claude/agents/lead.md": LINK_TARGET},
        "entries": {"scripts/run.sh": FileEntry(executable=True, content=SCRIPT)},
        "lock": LOCK,
    }
    return snapshot_of(**(arguments | changes))


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(LOCK_DRIFT.check(snapshot))
    assert all(finding.rule == "lock.drift" for finding in found)
    assert all(finding.line is None for finding in found)
    return [(finding.severity, finding.path, finding.message, finding.fix) for finding in found]


def test_reports_nothing_when_hub_matches_lock(snapshot_of: SnapshotFactory) -> None:
    assert findings_of(hub_as_locked(snapshot_of)) == []


def test_warns_not_adopted_when_lock_absent(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(files={"AGENTS.md": b"# Agents\n"}, lock=LockAbsent())

    assert findings_of(snapshot) == [
        (
            Severity.WARNING,
            "hub.lock",
            "not adopted: no hub.lock records this hub's files",
            "run hub sync --adopt",
        )
    ]


def test_reports_error_when_managed_file_deleted(snapshot_of: SnapshotFactory) -> None:
    snapshot = hub_as_locked(snapshot_of, files={"AGENTS.md": b"# Agents\n"})

    assert findings_of(snapshot) == [(Severity.ERROR, ".claude/settings.json", MISSING, SYNC_FIX)]


def test_reports_error_when_managed_bytes_differ(snapshot_of: SnapshotFactory) -> None:
    snapshot = hub_as_locked(
        snapshot_of,
        entries={"scripts/run.sh": FileEntry(executable=True, content=SCRIPT + b"echo more\n")},
    )

    assert findings_of(snapshot) == [
        (Severity.ERROR, "scripts/run.sh", "content differs from its hub.lock entry", SYNC_FIX)
    ]


def test_reports_error_when_only_executable_bit_differs(snapshot_of: SnapshotFactory) -> None:
    snapshot = hub_as_locked(
        snapshot_of, entries={"scripts/run.sh": FileEntry(executable=False, content=SCRIPT)}
    )

    assert findings_of(snapshot) == [
        (
            Severity.ERROR,
            "scripts/run.sh",
            "executable bit differs from its hub.lock entry (on disk -x, hub.lock +x)",
            SYNC_FIX,
        )
    ]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (FolderEntry(), "not a regular file; hub.lock records a file"),
        (
            LinkEntry(target="run.sh.real", outside=False),
            "not a regular file; hub.lock records a file",
        ),
    ],
    ids=["folder", "link"],
)
def test_reports_error_when_managed_file_not_regular(
    snapshot_of: SnapshotFactory, *, entry: FolderEntry | LinkEntry, message: str
) -> None:
    snapshot = hub_as_locked(snapshot_of, entries={"scripts/run.sh": entry})

    assert findings_of(snapshot) == [(Severity.ERROR, "scripts/run.sh", message, SYNC_FIX)]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"links": {".claude/agents/lead.md": "../../elsewhere/lead.md"}},
            "link target differs from its hub.lock entry"
            f" (on disk -> ../../elsewhere/lead.md, hub.lock -> {LINK_TARGET})",
        ),
        (
            {
                "files": {".claude/settings.json": SETTINGS, ".claude/agents/lead.md": b"# Lead\n"},
                "links": {},
            },
            "not a link; hub.lock records a link",
        ),
        ({"links": {}}, MISSING),
    ],
    ids=["retargeted", "replaced-by-file", "deleted"],
)
def test_reports_error_when_managed_link_retargeted_or_replaced(
    snapshot_of: SnapshotFactory, *, changes: dict[str, object], message: str
) -> None:
    snapshot = hub_as_locked(snapshot_of, **changes)

    found = [finding for finding in findings_of(snapshot) if finding[1] != "AGENTS.md"]
    assert found == [(Severity.ERROR, ".claude/agents/lead.md", message, SYNC_FIX)]


@pytest.mark.parametrize(
    "files",
    [
        {".claude/settings.json": SETTINGS, "AGENTS.md": b"# Our own agents\n"},
        {".claude/settings.json": SETTINGS},
    ],
    ids=["edited", "deleted"],
)
def test_ignores_seeded_when_edited_or_deleted(
    snapshot_of: SnapshotFactory, files: dict[str, bytes]
) -> None:
    assert findings_of(hub_as_locked(snapshot_of, files=files)) == []


def test_skips_absent_paths_when_hub_files_not_all_read(snapshot_of: SnapshotFactory) -> None:
    # An absent path may be one the read failed on: the runner reports that failure instead.
    snapshot = hub_as_locked(
        snapshot_of,
        files={"AGENTS.md": b"# Agents\n"},
        links={},
        entries={"scripts/run.sh": FileEntry(executable=False, content=SCRIPT)},
        problem="could not read the files: .claude: Permission denied",
    )

    assert findings_of(snapshot) == [
        (
            Severity.ERROR,
            "scripts/run.sh",
            "executable bit differs from its hub.lock entry (on disk -x, hub.lock +x)",
            SYNC_FIX,
        )
    ]


def test_warns_sync_pending_when_lock_older_than_pin(snapshot_of: SnapshotFactory) -> None:
    lock = a_lock(LOCK.files, platform_version="0.1.9")

    assert findings_of(hub_as_locked(snapshot_of, lock=lock)) == [
        (
            Severity.WARNING,
            "hub.lock",
            "sync pending: hub.lock was written by 0.1.9, hub.json pins 0.2.0",
            SYNC_FIX,
        )
    ]


def test_warns_downgrade_when_lock_newer_than_pin(snapshot_of: SnapshotFactory) -> None:
    lock = a_lock(LOCK.files, platform_version="1.0.0")

    assert findings_of(hub_as_locked(snapshot_of, lock=lock)) == [
        (
            Severity.WARNING,
            "hub.lock",
            "downgrade: hub.lock was written by 1.0.0, newer than the 0.2.0 hub.json pins",
            "pin 1.0.0 in hub.json, or run hub sync to downgrade",
        )
    ]


@pytest.mark.parametrize(
    ("locked", "state"),
    [("0.10.0", "downgrade"), ("0.02.0", None), ("0.1.10", "sync pending")],
    ids=["longer-newer", "leading-zero-equal", "longer-older"],
)
def test_compares_versions_as_numbers_when_digits_differ_in_length(
    snapshot_of: SnapshotFactory, *, locked: str, state: str | None
) -> None:
    # Against the pin 0.2.0 a string compare says 0.10.0 is older and 0.02.0 differs.
    lock = a_lock(LOCK.files, platform_version=locked)

    found = findings_of(hub_as_locked(snapshot_of, lock=lock))

    assert [message.split(":")[0] for _, _, message, _ in found] == (
        [] if state is None else [state]
    )


def test_reports_nothing_when_lock_version_equals_pin(snapshot_of: SnapshotFactory) -> None:
    lock = a_lock(LOCK.files, platform_version=PIN)

    assert findings_of(hub_as_locked(snapshot_of, lock=lock)) == []


@pytest.mark.parametrize(
    ("content", "problems"),
    [
        (b'{"lock_version": ', ["$: not valid JSON: Expecting value at line 1 column 18"]),
        (
            b'{"lock_version": 1, "platform_version": "0.2.0", "schema_version": 2,'
            b' "modules": [], "files": {"Makefile": {"ownership": "managed",'
            b' "executable": false}}}',
            ["schema_version: Input should be 1", "files.Makefile.sha256: Field required"],
        ),
    ],
    ids=["invalid-json", "entries"],
)
def test_reports_each_problem_when_lock_malformed(
    snapshot_of: SnapshotFactory, *, content: bytes, problems: list[str]
) -> None:
    state = lock_state(FileEntry(executable=False, content=content))

    assert isinstance(state, tuple)
    found = findings_of(snapshot_of(lock=state))
    assert found == [(Severity.ERROR, "hub.lock", problem, LOCK_WAY_OUT) for problem in problems]


@pytest.mark.parametrize(
    "entry",
    [
        LinkEntry(target="elsewhere.lock", outside=False),
        FolderEntry(),
        OtherEntry(kind="fifo"),
        FileEntry(executable=False, content=None),
    ],
    ids=["link", "folder", "fifo", "unread"],
)
def test_reports_not_regular_when_lock_is_link_folder_or_fifo(
    snapshot_of: SnapshotFactory, entry: LinkEntry | FolderEntry | OtherEntry | FileEntry
) -> None:
    state = lock_state(entry)

    assert state == LockNotRegular()
    assert findings_of(snapshot_of(lock=state)) == [
        (Severity.ERROR, "hub.lock", "not a regular file", LOCK_WAY_OUT)
    ]


def test_reads_lock_when_entry_regular() -> None:
    content = (
        b'{"files": {"hub.json": {"ownership": "seeded"}}, "lock_version": 1, "modules": [],'
        b' "platform_version": "0.2.0", "schema_version": 1}\n'
    )

    assert lock_state(None) == LockAbsent()
    assert lock_state(FileEntry(executable=False, content=content)) == a_lock(
        {"hub.json": SeededEntry(ownership="seeded")}
    )


@pytest.mark.parametrize(
    ("state", "paths"),
    [
        (LOCK, (".claude/agents/lead.md", ".claude/settings.json", "scripts/run.sh")),
        (LockAbsent(), ()),
        (LockNotRegular(), ()),
        ((ConfigProblem("$", "not valid JSON"),), ()),
        (None, ()),
    ],
    ids=["lock", "absent", "not-regular", "malformed", "not-read"],
)
def test_lists_managed_paths_when_lock_read(
    state: LockState | None, paths: tuple[str, ...]
) -> None:
    assert lock_paths(state) == paths


def test_reports_nothing_when_lock_not_read(snapshot_of: SnapshotFactory) -> None:
    # hub.lock could not be read: the runner reports the read's problem, never "not adopted".
    snapshot = snapshot_of(
        lock=None, problem="could not read the files: hub.lock: Permission denied"
    )

    assert findings_of(snapshot) == []


def test_declares_release_commit_read_when_rule_is_listed() -> None:
    # The CLI probes the tag only when a selected rule reads RELEASE_COMMIT (Q5), so
    # ``--only features.tracker`` probes nothing and ``lock.drift`` alone asks for it.
    assert LOCK_DRIFT.id == "lock.drift"
    assert LOCK_DRIFT.severity is Severity.ERROR
    assert sorted(read.name for read in LOCK_DRIFT.reads) == ["LOCK_PATHS", "RELEASE_COMMIT"]


def test_reports_missing_when_only_listing_failed(snapshot_of: SnapshotFactory) -> None:
    # Every path was read by path: only the listing failed, so an absent path is missing.
    snapshot = hub_as_locked(
        snapshot_of,
        files={"AGENTS.md": b"# Agents\n"},
        problem="could not list the files: git not found",
        paths_read=True,
    )

    assert findings_of(snapshot) == [(Severity.ERROR, ".claude/settings.json", MISSING, SYNC_FIX)]


def test_reports_unread_content_when_managed_file_not_read(snapshot_of: SnapshotFactory) -> None:
    snapshot = hub_as_locked(
        snapshot_of, entries={"scripts/run.sh": FileEntry(executable=True, content=None)}
    )

    assert findings_of(snapshot) == [
        (
            Severity.ERROR,
            "scripts/run.sh",
            "content was not read, so it cannot be compared with its hub.lock entry",
            "run hub doctor again",
        )
    ]


def test_cuts_link_targets_when_too_long_to_echo(snapshot_of: SnapshotFactory) -> None:
    on_disk = "../" + "a" * 200
    locked = "../../" + "b" * 200
    lock = a_lock({".claude/agents/lead.md": ManagedLinkEntry(ownership="managed", symlink=locked)})
    snapshot = snapshot_of(links={".claude/agents/lead.md": on_disk}, lock=lock)

    [(_, _, message, _)] = findings_of(snapshot)

    # Each target is cut to 80 characters, its last one an ellipsis.
    assert message == (
        "link target differs from its hub.lock entry"
        f" (on disk -> {on_disk[:79]}…, hub.lock -> {locked[:79]}…)"
    )


# The builder's config writes no repository, so the one in use is the default
# (docs/design/project-config.md); the tag of the builder's pin 0.2.0 is v0.2.0.
DEFAULT_REPOSITORY = "git+https://github.com/jroquette/agent-hub"
FORK = "git+https://github.com/acme/agent-hub-fork"
LOCKED = "0123456789abcdef0123456789abcdef01234567"
TAGGED = "fedcba9876543210fedcba9876543210fedcba98"


def hub_with_commit(
    snapshot_of: SnapshotFactory,
    probe: ReleaseProbe | None,
    *,
    repository: str = DEFAULT_REPOSITORY,
) -> DoctorSnapshot:
    """The hub ``LOCK`` records, its lock holding ``LOCKED``, with the CLI's tag probe result."""
    lock = a_lock(LOCK.files, platform_commit=LOCKED, platform_repository=repository)
    return replace(hub_as_locked(snapshot_of, lock=lock), release_probe=probe)


def only_finding(snapshot: DoctorSnapshot) -> Shown:
    found = findings_of(snapshot)
    assert len(found) == 1, found
    return found[0]


def test_reports_error_when_probed_commit_differs_from_lock(snapshot_of: SnapshotFactory) -> None:
    # The same hub whose tag names the locked commit is clean: only the difference is reported.
    assert findings_of(hub_with_commit(snapshot_of, ReleaseFound(commit=LOCKED))) == []

    severity, path, message, fix = only_finding(
        hub_with_commit(snapshot_of, ReleaseFound(commit=TAGGED))
    )

    assert (severity, path, fix) == (Severity.ERROR, "hub.lock", SYNC_FIX)
    assert LOCKED in message
    assert TAGGED in message


def test_reports_error_when_probed_tag_is_missing(snapshot_of: SnapshotFactory) -> None:
    severity, path, message, fix = only_finding(hub_with_commit(snapshot_of, ReleaseTagMissing()))

    assert (severity, path, fix) == (Severity.ERROR, "hub.lock", SYNC_FIX)
    assert "v0.2.0" in message
    assert LOCKED in message


type ProbeOf = Callable[[], ReleaseProbe | None]


@pytest.mark.parametrize(
    "probe_of",
    [lambda: ReleaseProbeFailed(reason="could not reach the platform repository"), lambda: None],
    ids=["unreachable", "not-probed"],
)
def test_reports_nothing_when_release_probe_failed(
    snapshot_of: SnapshotFactory, probe_of: ProbeOf
) -> None:
    # An unreachable remote is the CLI's one stderr note, never a finding (Q5).
    assert findings_of(hub_with_commit(snapshot_of, probe_of())) == []


@pytest.mark.parametrize(
    "probe_of",
    [lambda: ReleaseFound(commit=TAGGED), ReleaseTagMissing, lambda: None],
    ids=["found", "missing", "none"],
)
def test_reports_nothing_when_lock_has_no_commit(
    snapshot_of: SnapshotFactory, probe_of: ProbeOf
) -> None:
    # A v0.27.1 lock, or one a fresh hub init wrote: no finding, so a demo hub stays clean (Q21).
    snapshot = replace(hub_as_locked(snapshot_of), release_probe=probe_of())

    assert findings_of(snapshot) == []


def test_warns_when_lock_repository_differs_from_config(snapshot_of: SnapshotFactory) -> None:
    severity, path, message, fix = only_finding(hub_with_commit(snapshot_of, None, repository=FORK))

    assert (severity, path, fix) == (Severity.WARNING, "hub.lock", SYNC_FIX)
    assert FORK in message
    assert DEFAULT_REPOSITORY in message
