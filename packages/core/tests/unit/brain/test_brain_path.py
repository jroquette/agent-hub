from pathlib import PurePosixPath

import pytest

from agent_hub.core.brain.brain_path import (
    MAX_NOTE_BYTES,
    MAX_PATH_CHARS,
    BrainPathError,
    accept_destination,
    archive_destination,
    brain_relative,
    branch_slug,
    inbox_note,
    learning_branch,
)

TRAVERSALS = [
    "../hub.json",
    "/etc/passwd",
    "../x.md",
    "a/../../x.md",
    "a\\b.md",
    "auto/workspace/x.md",
    "x.txt",
    ".hidden/x.md",
    "",
    "a//b.md",
    "./x.md",
    "a/\x00.md",
    "a/.x.md",
]


@pytest.mark.parametrize("path", TRAVERSALS, ids=lambda path: repr(path))
def test_refuses_path_when_path_traversal_attempted(path: str) -> None:
    with pytest.raises(BrainPathError) as raised:
        brain_relative(path)

    assert raised.value.reason


@pytest.mark.parametrize("path", ["AUTO/x.md", "Auto/x.md", "aUtO/workspace/x.md"])
def test_refuses_path_when_personal_folder_differs_in_case(path: str) -> None:
    with pytest.raises(BrainPathError, match="personal memory"):
        brain_relative(path)


def test_refuses_path_when_path_longer_than_cap() -> None:
    with pytest.raises(BrainPathError, match="long"):
        brain_relative("a/" * (MAX_PATH_CHARS // 2) + "x.md")


def test_refuses_path_when_too_many_segments() -> None:
    with pytest.raises(BrainPathError, match="deep"):
        brain_relative("a/" * 16 + "x.md")


@pytest.mark.parametrize(
    "path", ["index.md", "decisions/index.md", "features/demo/plan.md", "learnings/a-b_c.d.md"]
)
def test_accepts_path_when_note_nested(path: str) -> None:
    assert brain_relative(path) == PurePosixPath(path)


def test_caps_note_size_when_constant_read() -> None:
    assert MAX_NOTE_BYTES == 256 * 1024


def test_returns_brain_path_when_note_in_inbox() -> None:
    assert inbox_note("brain/_inbox/testing-x.md") == PurePosixPath("_inbox/testing-x.md")


@pytest.mark.parametrize(
    "note_path",
    [
        "brain/learnings/x.md",
        "brain/_inbox/_archive/x.md",
        "brain/_inbox/_Archive/x.md",
        "_inbox/x.md",
        "brain/_inbox/../hub.md",
        "agent-hub/AGENTS.md",
    ],
)
def test_refuses_note_when_outside_inbox(note_path: str) -> None:
    with pytest.raises(BrainPathError):
        inbox_note(note_path)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("learnings/", "learnings/testing-x.md"),
        ("learnings/gotchas", "learnings/gotchas/testing-x.md"),
        ("learnings/gotchas/testing-other.md", "learnings/gotchas/testing-other.md"),
        ("playbooks/", "playbooks/testing-x.md"),
    ],
)
def test_names_destination_when_folder_allowed(target: str, expected: str) -> None:
    assert accept_destination(target, PurePosixPath("_inbox/testing-x.md")) == expected


@pytest.mark.parametrize(
    "target",
    [
        "decisions/",
        "decisions/index.md",
        "_inbox/",
        "_inbox/_archive/x.md",
        "auto/workspace/",
        "../outside/",
        "/abs/",
        "",
        "learnings/../decisions/",
        "top-level.md",
    ],
)
def test_refuses_destination_when_folder_is_decisions_or_inbox(target: str) -> None:
    with pytest.raises(BrainPathError):
        accept_destination(target, PurePosixPath("_inbox/testing-x.md"))


@pytest.mark.parametrize(
    ("target", "folder"),
    [
        pytest.param("Decisions/", "Decisions", id="decisions"),
        pytest.param("DECISIONS/x.md", "DECISIONS", id="decisions_note"),
        pytest.param("_Inbox/", "_Inbox", id="inbox"),
    ],
)
def test_refuses_destination_when_reserved_folder_differs_in_case(
    target: str, folder: str
) -> None:
    with pytest.raises(BrainPathError) as refused:
        accept_destination(target, PurePosixPath("_inbox/testing-x.md"))

    assert refused.value.reason == f"A learning cannot be accepted into {folder}/"


def test_refuses_destination_when_personal_folder_differs_in_case() -> None:
    with pytest.raises(BrainPathError, match="personal memory"):
        accept_destination("Auto/workspace/", PurePosixPath("_inbox/testing-x.md"))


def test_names_archive_when_note_rejected() -> None:
    assert (
        archive_destination(PurePosixPath("_inbox/testing-x.md")) == "_inbox/_archive/testing-x.md"
    )


@pytest.mark.parametrize(
    ("note", "slug"),
    [
        ("_inbox/testing-x.md", "testing-x"),
        ("_inbox/Onboard Proposal: Demo!.md", "onboard-proposal-demo"),
        ("_inbox/2026-10-12_a__b.md", "2026-10-12-a-b"),
        ("_inbox/___.md", "note"),
    ],
)
def test_slugs_note_when_branch_named(note: str, slug: str) -> None:
    assert branch_slug(PurePosixPath(note)) == slug


def test_clips_slug_when_note_name_long() -> None:
    assert len(branch_slug(PurePosixPath("_inbox/" + "a" * 200 + ".md"))) == 50


def test_names_branch_when_learning_accepted() -> None:
    branch = learning_branch(
        branch_prefix="roquettejh/", action="accept", note=PurePosixPath("_inbox/testing-x.md")
    )

    assert branch == "roquettejh/learning-accept-testing-x"
