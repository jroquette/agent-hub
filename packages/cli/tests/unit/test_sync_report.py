import hashlib

import pytest

from agent_hub.cli.sync_report import UP_TO_DATE, change_lines, conflict_lines
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import build_hub_lock
from agent_hub.core.hub_files.plan_init import FileWrite, PathProblem
from agent_hub.core.hub_files.plan_sync import (
    ContentConflict,
    SyncChange,
    SyncConflicts,
    SyncPlan,
    SyncProblem,
    Verb,
)
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.testing.builders import a_hub_document

WAY_OUT = (
    "move the change to an extension file (hub.json, a *.project.* file, Makefile.project),"
    " restore or delete the file, then re-run hub sync"
)


def a_plan(
    changes: dict[str, Verb] | None = None,
    *,
    leftovers: tuple[str, ...] = (),
    lock_written: bool = False,
) -> SyncPlan:
    """A plan with ``changes`` (path → verb), ``leftovers``, and a lock write when asked."""
    document = a_hub_document()
    del document["modules"]
    lock = build_hub_lock(
        rendered=RenderedHub(files=(), links=()), config=HubConfig.model_validate(document)
    )
    changed = changes or {}
    writes = [
        FileWrite(path=path, content=b"x\n", executable=False)
        for path, verb in changed.items()
        if verb is not Verb.DELETED
    ]
    if lock_written:
        writes.append(FileWrite(path="hub.lock", content=b"{}\n", executable=False))
    return SyncPlan(
        leftovers=leftovers,
        deletes=tuple(path for path, verb in changed.items() if verb is Verb.DELETED),
        folders=(),
        writes=tuple(writes),
        changes=tuple(SyncChange(path=path, verb=verb) for path, verb in changed.items()),
        lock=lock,
        lock_written=lock_written,
    )


def conflicts(*problems: SyncProblem) -> SyncConflicts:
    return SyncConflicts(problems=problems)


def text_conflict(on_disk: str, render: str, *, path: str = "Makefile") -> ContentConflict:
    return ContentConflict(path=path, on_disk=on_disk.encode(), render=render.encode())


def body(lines: list[str]) -> list[str]:
    """The report lines without the way-out line, which the report must end with."""
    assert lines[-1] == WAY_OUT
    return lines[:-1]


ALL_VERBS = {
    "c.md": Verb.CREATED,
    "a.md": Verb.RESTORED,
    "d/e.md": Verb.DELETED,
    "b.md": Verb.UPDATED,
}


@pytest.mark.parametrize("check", [False, True], ids=["apply", "check"])
def test_prints_up_to_date_when_plan_empty(*, check: bool) -> None:
    assert change_lines(a_plan(), check=check) == [UP_TO_DATE]
    assert UP_TO_DATE == "up to date"


def test_prints_changes_sorted_then_leftovers_then_lock_when_applied() -> None:
    plan = a_plan(ALL_VERBS, leftovers=("a/.x.hub-tmp-1", "b/.y.hub-tmp-2"), lock_written=True)

    assert change_lines(plan, check=False) == [
        "restored a.md",
        "updated b.md",
        "created c.md",
        "deleted d/e.md",
        "removed 2 leftover temporary files",
        "updated hub.lock",
    ]


def test_prefixes_would_when_checking() -> None:
    plan = a_plan(ALL_VERBS, leftovers=("a/.x.hub-tmp-1",), lock_written=True)

    assert change_lines(plan, check=True) == [
        "would restore a.md",
        "would update b.md",
        "would create c.md",
        "would delete d/e.md",
        "would remove 1 leftover temporary files",
        "would update hub.lock",
    ]


@pytest.mark.parametrize(
    ("check", "expected"),
    [(False, ["updated hub.lock"]), (True, ["would update hub.lock"])],
    ids=["apply", "check"],
)
def test_prints_only_lock_line_when_lock_alone_changes(*, check: bool, expected: list[str]) -> None:
    assert change_lines(a_plan(lock_written=True), check=check) == expected


def test_prints_only_leftover_line_when_leftover_alone() -> None:
    plan = a_plan(leftovers=("a/.x.hub-tmp-1",))

    assert change_lines(plan, check=False) == ["removed 1 leftover temporary files"]


def test_shows_unified_diff_with_labels_when_text_differs() -> None:
    on_disk = "".join(f"line {number}\n" for number in range(1, 11))
    render = on_disk.replace("line 5\n", "line five\n")

    lines = body(conflict_lines(conflicts(text_conflict(on_disk, render))))

    assert lines == [
        "--- Makefile (on disk)",
        "+++ Makefile (render)",
        "@@ -2,7 +2,7 @@",
        " line 2",
        " line 3",
        " line 4",
        "-line 5",
        "+line five",
        " line 6",
        " line 7",
        " line 8",
    ]


def test_marks_missing_newline_when_only_last_line_end_differs() -> None:
    lines = body(conflict_lines(conflicts(text_conflict("a\nb", "a\nb\n"))))

    assert lines == [
        "--- Makefile (on disk)",
        "+++ Makefile (render)",
        "@@ -1,2 +1,2 @@",
        " a",
        "-b",
        "\\ No newline at end of file",
        "+b",
    ]


def test_escapes_diff_line_when_unprintable_but_keeps_tabs() -> None:
    lines = body(conflict_lines(conflicts(text_conflict("\tx\r\n", "\tx\n"))))

    assert lines[3:] == ['"-\\tx\\r"', "+\tx"]


def test_caps_diff_at_200_lines_when_long() -> None:
    on_disk = "".join(f"old {number}\n" for number in range(300))
    render = "".join(f"new {number}\n" for number in range(300))

    lines = body(conflict_lines(conflicts(text_conflict(on_disk, render))))

    # Two labels, one hunk header, 300 removed and 300 added lines: 603 in all.
    assert len(lines) == 201
    assert lines[:3] == ["--- Makefile (on disk)", "+++ Makefile (render)", "@@ -1,300 +1,300 @@"]
    assert lines[199] == "-old 196"
    assert lines[200] == "… 403 more lines"


@pytest.mark.parametrize(
    ("on_disk", "render"),
    [(b"caf\xe9\n", b"cafe\n"), (b"text\n", b"te\x00xt\n")],
    ids=["not-utf8-on-disk", "nul-in-render"],
)
def test_prints_binary_line_when_not_utf8_or_nul(on_disk: bytes, render: bytes) -> None:
    conflict = ContentConflict(path="bin/tool", on_disk=on_disk, render=render)

    lines = body(conflict_lines(conflicts(conflict)))

    disk_hex = hashlib.sha256(on_disk).hexdigest()[:12]
    render_hex = hashlib.sha256(render).hexdigest()[:12]
    assert lines == [
        f"bin/tool: binary content differs (on disk sha256 {disk_hex}, render {render_hex})"
    ]


def test_prints_cause_line_per_path_when_problem_has_cause() -> None:
    reported = conflicts(
        PathProblem("a.py", "executable bit differs (on disk -x, render +x)"),
        text_conflict("x\n", "y\n", path="b.md"),
        PathProblem(".claude/skills/s", "link target differs (on disk -> x, render -> y)"),
    )

    lines = body(conflict_lines(reported))

    assert lines == [
        "a.py: executable bit differs (on disk -x, render +x)",
        "--- b.md (on disk)",
        "+++ b.md (render)",
        "@@ -1 +1 @@",
        "-x",
        "+y",
        ".claude/skills/s: link target differs (on disk -> x, render -> y)",
    ]


def test_escapes_path_when_unprintable() -> None:
    reported = conflicts(
        PathProblem("a\nb.md", "resolves outside the hub"),
        text_conflict("x\n", "y\n", path='q"\x1b.md'),
    )

    lines = body(conflict_lines(reported))

    assert lines[0] == '"a\\nb.md": resolves outside the hub'
    assert lines[1:3] == ['--- "q\\"\\u001b.md" (on disk)', '+++ "q\\"\\u001b.md" (render)']
    plan = a_plan({"a\nb.md": Verb.CREATED})
    assert change_lines(plan, check=False) == ['created "a\\nb.md"']
    assert change_lines(plan, check=True) == ['would create "a\\nb.md"']


def test_ends_with_way_out_when_conflicts_reported() -> None:
    lines = conflict_lines(conflicts(PathProblem("a.md", "resolves outside the hub")))

    assert lines == ["a.md: resolves outside the hub", WAY_OUT]
