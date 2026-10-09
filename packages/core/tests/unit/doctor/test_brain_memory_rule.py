"""``brain.memory``: personal memory in ``brain/auto/workspace/`` stays out of git (AGH-48).

(a) On a listing git made, each listed path under ``brain/auto/workspace/`` but its ``.gitkeep``
is tracked or not ignored: one warning per path, at most 10, then one ``N more`` at the folder;
a walked listing skips (a). (b) ``.gitignore`` has a line covering the folder (``brain``,
``brain/auto`` or ``brain/auto/workspace``, with or without a leading ``/`` and a trailing
``/``, ``/*`` or ``/**``; comment and ``!`` lines never cover), else one warning at it; absent
(not listed, no entry) when every fixed path was read: one warning at ``.`` (plan E7: an
untracked, self-ignored ``.gitignore`` reads as absent). A link or non-text ``.gitignore`` and a
hub listing problem give none. No memory file's content is shown. Every text here is synthetic
(AGENTS.md rule 4).
"""

from collections.abc import Callable

import pytest

from agent_hub.core.doctor.brain_memory_rule import BRAIN_MEMORY
from agent_hub.core.doctor.finding import Finding, Read
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, Severity
from agent_hub.core.hub_files.tree_snapshot import FileEntry

type SnapshotFactory = Callable[..., DoctorSnapshot]

COVERING_GITIGNORE = b"brain/auto/workspace/*\n!brain/auto/workspace/.gitkeep\n"
GITKEEP = "brain/auto/workspace/.gitkeep"
LISTED_MESSAGE = "personal memory file is tracked or not ignored by git"
IGNORE_MESSAGE = ".gitignore does not ignore brain/auto/workspace/ (personal memory)"
FIX = (
    "add brain/auto/workspace/* and !brain/auto/workspace/.gitkeep to .gitignore;"
    " if committed, git rm --cached the file (it stays on disk)"
)
CANARY = "ZZ-PERSONAL-CANARY-48"


def found(snapshot: DoctorSnapshot) -> list[Finding]:
    return list(BRAIN_MEMORY.check(snapshot))


def warning(path: str, message: str) -> Finding:
    return Finding(
        rule="brain.memory",
        severity=Severity.WARNING,
        path=path,
        line=None,
        message=message,
        fix=FIX,
    )


def listed_memory(path: str) -> Finding:
    return warning(path, LISTED_MESSAGE)


IGNORE_FINDING = warning(".gitignore", IGNORE_MESSAGE)


def test_declares_design_fields_when_brain_memory_rule_read() -> None:
    assert BRAIN_MEMORY.id == "brain.memory"
    assert BRAIN_MEMORY.severity is Severity.WARNING
    assert BRAIN_MEMORY.reads == frozenset({Read.HUB_LISTING})
    assert BRAIN_MEMORY.module is None
    assert RULE_IDS[-1] == "brain.memory"


def test_warns_each_listed_memory_file_when_git_listed(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        files={
            ".gitignore": COVERING_GITIGNORE,
            GITKEEP: b"",
            "brain/auto/workspace/MEMORY.md": b"- synthetic preference\n",
            "brain/auto/workspace/prefs.md": b"synthetic topic\n",
        },
        listed_by_git=True,
    )

    assert found(snapshot) == [
        listed_memory("brain/auto/workspace/MEMORY.md"),
        listed_memory("brain/auto/workspace/prefs.md"),
    ]


def test_keeps_listing_order_when_memory_files_listed(snapshot_of: SnapshotFactory) -> None:
    # The rule follows the listing as given; it neither sorts nor dedupes it.
    order = ("brain/auto/workspace/z.md", "brain/auto/workspace/a.md")
    snapshot = snapshot_of(
        files={".gitignore": COVERING_GITIGNORE} | dict.fromkeys(order, b"x\n"),
        listed=(".gitignore", *order),
        listed_by_git=True,
    )

    assert found(snapshot) == [listed_memory(path) for path in order]


@pytest.mark.parametrize(
    ("count", "more"),
    [
        pytest.param(10, [], id="ten"),
        pytest.param(
            11, ["1 more personal memory file is tracked or not ignored by git"], id="eleven"
        ),
        pytest.param(
            12, ["2 more personal memory files are tracked or not ignored by git"], id="twelve"
        ),
    ],
)
def test_caps_listed_memory_findings_when_more_than_ten(
    snapshot_of: SnapshotFactory, count: int, more: list[str]
) -> None:
    paths = [f"brain/auto/workspace/m{index:02}.md" for index in range(count)]
    snapshot = snapshot_of(
        files={".gitignore": COVERING_GITIGNORE, GITKEEP: b""} | dict.fromkeys(paths, b"x\n"),
        listed_by_git=True,
    )

    # A literal 10, not the module's constant, so a changed cap fails here.
    assert found(snapshot) == [listed_memory(path) for path in paths[:10]] + [
        warning("brain/auto/workspace/", message) for message in more
    ]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(GITKEEP, [], id="gitkeep_only"),
        pytest.param("brain/auto/workspace-old/x.md", [], id="sibling_folder"),
        pytest.param("brain/auto/agent-context.md", [], id="agent_context"),
        pytest.param(
            "brain/auto/workspace/sub/x.md",
            [listed_memory("brain/auto/workspace/sub/x.md")],
            id="nested",
        ),
    ],
)
def test_passes_listed_paths_when_none_is_memory(
    snapshot_of: SnapshotFactory, path: str, expected: list[Finding]
) -> None:
    snapshot = snapshot_of(
        files={".gitignore": COVERING_GITIGNORE, path: b"x\n"}, listed_by_git=True
    )

    assert found(snapshot) == expected


@pytest.mark.parametrize(
    "gitignore",
    [
        pytest.param(b"brain/auto/workspace/*\n", id="star"),
        pytest.param(b"/brain/auto/workspace/\n", id="rooted_slash"),
        pytest.param(b"brain/auto/workspace/**\n", id="double_star"),
        pytest.param(b"brain/auto/\n", id="auto"),
        pytest.param(b"brain/\n", id="brain"),
        pytest.param(b"brain/auto/workspace/*  \n", id="trailing_space"),
        pytest.param(b"node_modules/\r\nbrain/auto/workspace/*\r\n", id="crlf"),
    ],
)
def test_passes_covering_gitignore_line_when_hub_listed(
    snapshot_of: SnapshotFactory, gitignore: bytes
) -> None:
    snapshot = snapshot_of(files={".gitignore": gitignore, GITKEEP: b""}, listed_by_git=True)

    assert found(snapshot) == []


@pytest.mark.parametrize(
    "gitignore",
    [
        pytest.param(b"brain/auto/workspace/session-snapshot.md\n", id="snapshot_only"),
        pytest.param(b"# brain/auto/workspace/*\n", id="comment"),
        pytest.param(b"!brain/auto/workspace/*\n", id="negation"),
        pytest.param(b"", id="empty"),
    ],
)
def test_warns_gitignore_when_no_line_covers(
    snapshot_of: SnapshotFactory, gitignore: bytes
) -> None:
    snapshot = snapshot_of(files={".gitignore": gitignore, GITKEEP: b""}, listed_by_git=True)

    assert found(snapshot) == [IGNORE_FINDING]


def test_warns_absent_gitignore_when_paths_read(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(files={GITKEEP: b""}, listed_by_git=True)

    assert found(snapshot) == [warning(".", IGNORE_MESSAGE)]


@pytest.mark.parametrize(
    "case",
    [
        pytest.param({"files": {GITKEEP: b""}, "paths_read": False}, id="paths_not_read"),
        pytest.param({"files": {GITKEEP: b""}, "links": {".gitignore": "x"}}, id="link"),
        pytest.param({"files": {GITKEEP: b"", ".gitignore": b"\xff"}}, id="not_utf8"),
        pytest.param({"files": {GITKEEP: b"", ".gitignore": b"brain/\x00"}}, id="nul"),
    ],
)
def test_skips_gitignore_when_not_read_or_not_text(
    snapshot_of: SnapshotFactory, case: dict[str, object]
) -> None:
    snapshot = snapshot_of(listed_by_git=True, **case)

    assert found(snapshot) == []


@pytest.mark.parametrize(
    ("gitignore", "expected"),
    [
        pytest.param(COVERING_GITIGNORE, [], id="covering"),
        pytest.param(b"node_modules/\n", [IGNORE_FINDING], id="not_covering"),
    ],
)
def test_skips_listed_memory_when_listing_walked(
    snapshot_of: SnapshotFactory, gitignore: bytes, expected: list[Finding]
) -> None:
    snapshot = snapshot_of(
        files={
            ".gitignore": gitignore,
            GITKEEP: b"",
            "brain/auto/workspace/MEMORY.md": b"- synthetic preference\n",
        },
        listed_by_git=False,
    )

    assert found(snapshot) == expected


def test_yields_nothing_when_hub_listing_problem(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        listed=(),
        entries={
            "brain/auto/workspace/MEMORY.md": FileEntry(executable=False, content=b"x\n"),
            "brain/auto/workspace/prefs.md": FileEntry(executable=False, content=b"y\n"),
        },
        problem="could not list the files: x",
        listed_by_git=True,
    )

    assert found(snapshot) == []


@pytest.mark.parametrize(
    "gitignore",
    [
        pytest.param(COVERING_GITIGNORE, id="covering"),
        pytest.param(b"node_modules/\n", id="not_covering"),
    ],
)
def test_shows_no_memory_content_when_memory_listed(
    snapshot_of: SnapshotFactory, gitignore: bytes
) -> None:
    snapshot = snapshot_of(
        files={
            ".gitignore": gitignore,
            "brain/auto/workspace/prefs.md": f"{CANARY}\n".encode(),
        },
        listed_by_git=True,
    )

    findings = found(snapshot)

    assert listed_memory("brain/auto/workspace/prefs.md") in findings
    assert all(
        CANARY not in str(value)
        for finding in findings
        for value in (finding.path, finding.line, finding.message, finding.fix)
    )
