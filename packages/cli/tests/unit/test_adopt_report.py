import pytest

from agent_hub.cli.adopt_report import listing_lines, refusal_lines
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import build_hub_lock
from agent_hub.core.hub_files.plan_adopt import (
    ACCEPT_CONFLICT,
    ACCEPT_NOT_LISTED,
    AdoptPlan,
    AdoptRefusal,
    ContentDifference,
    LinkDifference,
    Listed,
    MigrationListing,
)
from agent_hub.core.hub_files.plan_init import PathProblem
from agent_hub.core.hub_files.plan_sync import ContentConflict, SyncProblem
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.testing.builders import a_hub_document

ADOPT_LISTED_WAY_OUT = (
    "take the template with --accept <path>, or move the change to an extension file, then re-run"
)
ADOPT_CONFLICT_WAY_OUT = (
    "move the change to an extension file (hub.json, a *.project.* file, Makefile.project),"
    " restore or delete the conflicting file, or take the template of a listed path with"
    " --accept <path>, then re-run hub sync --adopt"
)


def a_plan(*listed: Listed, conflicts: tuple[SyncProblem, ...] = ()) -> AdoptPlan:
    """An adopt plan that leaves ``listed`` and ``conflicts`` as they are and does nothing else."""
    document = a_hub_document()
    del document["modules"]
    lock = build_hub_lock(
        rendered=RenderedHub(files=(), links=()), config=HubConfig.model_validate(document)
    )
    return AdoptPlan(
        leftovers=(),
        deletes=(),
        folders=(),
        writes=(),
        changes=(),
        lock=lock,
        lock_written=False,
        listed=listed,
        conflicts=conflicts,
    )


def content(
    on_disk: bytes,
    render: bytes,
    *,
    path: str = "Makefile",
    on_disk_executable: bool = False,
    render_executable: bool = False,
) -> ContentDifference:
    return ContentDifference(
        path=path,
        on_disk=on_disk,
        render=render,
        on_disk_executable=on_disk_executable,
        render_executable=render_executable,
    )


def body(lines: list[str], way_out: str = ADOPT_LISTED_WAY_OUT) -> list[str]:
    """The listing without the way-out line, which it must end with."""
    assert lines[-1] == way_out
    return lines[:-1]


@pytest.mark.parametrize(
    ("on_disk", "render", "expected"),
    [
        (b"a\nb\nc\n", b"a\nB\nc\nd\n", "Makefile: +2 -1 lines"),
        (b"a\nb\nc\n", b"a\n", "Makefile: +0 -2 lines"),
        # Lines split on "\n" only: a "\r" or a missing last newline makes a line differ.
        (b"a\r\nb", b"a\nb\n", "Makefile: +2 -2 lines"),
    ],
    ids=["replaced-and-added", "removed", "line-ends"],
)
def test_counts_added_and_removed_lines_when_text_differs(
    on_disk: bytes, render: bytes, expected: str
) -> None:
    assert body(listing_lines(a_plan(content(on_disk, render)))) == [expected]


@pytest.mark.parametrize(
    ("on_disk", "render", "expected"),
    [
        (b"x\n", b"x\n", "guard.py: +0 -0 lines, executable bit differs (on disk +x, render -x)"),
        (b"x\n", b"y\n", "guard.py: +1 -1 lines, executable bit differs (on disk +x, render -x)"),
        # Equal bytes are no content difference, text or not.
        (b"\0", b"\0", "guard.py: +0 -0 lines, executable bit differs (on disk +x, render -x)"),
    ],
    ids=["bit-only", "bit-and-text", "bit-only-binary"],
)
def test_names_bit_when_only_executable_differs(
    on_disk: bytes, render: bytes, expected: str
) -> None:
    difference = content(on_disk, render, path="guard.py", on_disk_executable=True)

    assert body(listing_lines(a_plan(difference))) == [expected]


@pytest.mark.parametrize(
    ("on_disk", "render", "on_disk_executable", "expected"),
    [
        (b"caf\xe9\n", b"cafe\n", False, "logo.png: binary content differs"),
        (b"text\n", b"te\x00xt\n", False, "logo.png: binary content differs"),
        (
            b"\x89PNG",
            b"\x89PNG\x00",
            True,
            "logo.png: binary content differs, executable bit differs (on disk +x, render -x)",
        ),
    ],
    ids=["not-utf8-on-disk", "nul-in-render", "binary-and-bit"],
)
def test_names_binary_when_content_not_text(
    on_disk: bytes, render: bytes, *, on_disk_executable: bool, expected: str
) -> None:
    difference = content(on_disk, render, path="logo.png", on_disk_executable=on_disk_executable)

    assert body(listing_lines(a_plan(difference))) == [expected]


def test_names_targets_when_link_differs() -> None:
    plan = a_plan(
        LinkDifference(path=".claude/skills/s", on_disk_target="../x", render_target="../y"),
        LinkDifference(path="a\nb", on_disk_target="t\x1b", render_target="u"),
    )

    assert body(listing_lines(plan)) == [
        ".claude/skills/s: link target differs (on disk -> ../x, render -> ../y)",
        # An unprintable path or target shows the line as a JSON string, as sync does.
        '"\\"a\\\\nb\\": link target differs (on disk -> t\\u001b, render -> u)"',
    ]


def test_names_link_and_count_when_migration_listed() -> None:
    plan = a_plan(
        MigrationListing(path=".claude/skills", on_disk_target="../plugin/skills", link_count=3)
    )

    assert body(listing_lines(plan)) == [
        ".claude/skills: migration: directory link -> ../plugin/skills, rendered as 3 links"
    ]


def test_ends_with_way_out_when_listing_printed() -> None:
    clash = PathProblem("a.py", "resolves outside the hub")
    diff = ContentConflict(path="b.md", on_disk=b"x\n", render=b"y\n")
    listed = content(b"x\n", b"y\n")

    assert listing_lines(a_plan()) == []
    assert listing_lines(a_plan(listed)) == ["Makefile: +1 -1 lines", ADOPT_LISTED_WAY_OUT]
    # Listings first, then the conflicts as sync prints them, then one way out for both.
    assert listing_lines(a_plan(listed, conflicts=(clash, diff))) == [
        "Makefile: +1 -1 lines",
        "a.py: resolves outside the hub",
        "--- b.md (on disk)",
        "+++ b.md (render)",
        "@@ -1 +1 @@",
        "-x",
        "+y",
        ADOPT_CONFLICT_WAY_OUT,
    ]
    # A migration held back by a conflict under it is not listed: fixing it lists it on re-run.
    assert listing_lines(a_plan(conflicts=(clash,))) == [
        "a.py: resolves outside the hub",
        ADOPT_CONFLICT_WAY_OUT,
    ]


def test_names_each_refused_path_when_accept_refused() -> None:
    under = f"{ACCEPT_NOT_LISTED}: a conflict under it (.claude/skills/a, .claude/skills/b)"
    refusal = AdoptRefusal(
        refused=(
            PathProblem(".claude/skills", under),
            PathProblem("./Makefile", ACCEPT_NOT_LISTED),
            PathProblem("a.py", ACCEPT_CONFLICT),
            PathProblem("q\nr", ACCEPT_NOT_LISTED),
        )
    )

    assert refusal_lines(refusal) == [
        "--accept .claude/skills: not listed by this run: a conflict under it"
        " (.claude/skills/a, .claude/skills/b)",
        "--accept ./Makefile: not listed by this run",
        "--accept a.py: a conflict; --accept takes only listed differences and migrations",
        '--accept "q\\nr": not listed by this run',
    ]
