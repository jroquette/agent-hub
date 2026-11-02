"""``hub doctor --fix`` for ``brain.leak``: brain notes rewritten so no leak is left.

A note that quotes a few repo lines gets one pointer per run of leaked lines; a promoted draft
(half or more of its lines in the repo) becomes a stub naming the repo file. Every text here is
synthetic (AGENTS.md rule 4).

An ADR draft whose lines a repo holds only under ``docs/adr/`` is no leak, so it is left as it is.
"""

from collections.abc import Callable
from dataclasses import replace

from agent_hub.core.doctor import brain_leak_fix, brain_leak_rule
from agent_hub.core.doctor.brain_leak_fix import brain_leak_edits
from agent_hub.core.doctor.brain_leak_rule import BRAIN_LEAK
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_files.tree_snapshot import FileEntry

type SnapshotFactory = Callable[..., DoctorSnapshot]

NOTE = "brain/notes/widgets.md"
PLAN = "brain/f/plan.md"
_FILLER = "Synthetic note: the widget queue drains before the gear spins up again and again"


def sentence(length: int, *, tag: str = "a") -> str:
    text = (f"{tag} {_FILLER} " * (length // len(_FILLER) + 2))[:length]
    return text[:-1] + "." if text.endswith(" ") else text


def fixed(snapshot: DoctorSnapshot) -> DoctorSnapshot:
    """The snapshot with every edit applied to the hub's files."""
    entries = dict(snapshot.hub.entries)
    for edit in brain_leak_edits(snapshot):
        entries[edit.path] = FileEntry(executable=False, content=edit.text.encode())
    return replace(snapshot, hub=replace(snapshot.hub, entries=entries))


def test_points_at_repo_line_when_note_quotes_few_lines(snapshot_of: SnapshotFactory) -> None:
    copied = sentence(70)
    own = [sentence(70, tag=f"own{n}") for n in range(4)]
    note = f"# Widgets\n\n{own[0]}\n  {copied}\n{own[1]}\n{own[2]}\n{own[3]}\n"
    snapshot = snapshot_of(
        files={NOTE: note.encode()},
        repos={"demo-api": {"docs/a.md": f"intro\n{copied}\n".encode()}},
    )

    (edit,) = brain_leak_edits(snapshot)

    assert edit.path == NOTE
    assert edit.replaced == 1
    assert edit.promoted_to is None
    assert edit.text == note.replace(f"  {copied}", "  [in ../demo-api/docs/a.md:2]")
    assert list(BRAIN_LEAK.check(fixed(snapshot))) == []


def test_merges_run_when_leaked_lines_split_by_blanks(snapshot_of: SnapshotFactory) -> None:
    one, two = sentence(70, tag="one"), sentence(70, tag="two")
    own = [sentence(70, tag=f"own{n}") for n in range(4)]
    note = "\r\n".join([own[0], one, "", two, own[1], own[2], own[3]]) + "\r\n"
    snapshot = snapshot_of(
        files={NOTE: note.encode()},
        repos={"demo-api": {"docs/a.md": f"{one}\n\n{two}\n".encode()}},
    )

    (edit,) = brain_leak_edits(snapshot)

    expected = [own[0], "[in ../demo-api/docs/a.md:1-3]", own[1], own[2], own[3]]
    assert edit.text == "\r\n".join(expected) + "\r\n"
    assert edit.replaced == 2


def test_stubs_note_when_draft_promoted(snapshot_of: SnapshotFactory) -> None:
    lines = [sentence(70, tag=f"l{n}") for n in range(4)]
    draft = "---\ntitle: draft\n---\n# Draft\n\n" + "\n".join(lines) + "\nshort own line\n"
    snapshot = snapshot_of(
        files={"brain/features/f/ux-spec-draft.md": draft.encode()},
        repos={"demo-api": {"docs/design/x.md": ("\n".join(lines[:3]) + "\n").encode()}},
    )

    (edit,) = brain_leak_edits(snapshot)

    assert edit.promoted_to == "../demo-api/docs/design/x.md"
    assert edit.replaced == 3
    assert edit.text.startswith("---\ntitle: draft\n---\n\n# ux-spec-draft\n")
    assert "Promoted to `../demo-api/docs/design/x.md`" in edit.text
    assert list(BRAIN_LEAK.check(fixed(snapshot))) == []


def test_fixes_every_brain_file_when_line_repeated(snapshot_of: SnapshotFactory) -> None:
    line = sentence(64)
    own = [sentence(70, tag=f"own{n}") for n in range(3)]
    body = "\n".join(own)
    snapshot = snapshot_of(
        files={
            "brain/a.md": f"{body}\n{line}\n".encode(),
            "brain/b.md": f"{line}\n{body}\n".encode(),
        },
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert [edit.path for edit in brain_leak_edits(snapshot)] == ["brain/a.md", "brain/b.md"]
    assert list(BRAIN_LEAK.check(fixed(snapshot))) == []


def test_leaves_fenced_and_hub_files_when_fixing(snapshot_of: SnapshotFactory) -> None:
    line = sentence(70)
    snapshot = snapshot_of(
        files={NOTE: f"```\n{line}\n```\n".encode(), "docs/guide.md": f"{line}\n".encode()},
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert brain_leak_edits(snapshot) == ()


def test_returns_nothing_when_no_repo_checked_out(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(files={NOTE: f"{sentence(70)}\n".encode()}, repos={"demo-api": None})

    assert brain_leak_edits(snapshot) == ()


def test_leaves_draft_unchanged_when_only_adr_folder_holds_its_lines(
    snapshot_of: SnapshotFactory,
) -> None:
    lines = [sentence(70, tag=f"l{n}") for n in range(4)]
    draft = "---\ntitle: draft\n---\n# Draft\n\n" + "\n".join(lines) + "\nshort own line\n"
    own = [sentence(70, tag=f"own{n}") for n in range(3)]
    plan = "\n".join(["# Plan", own[0], lines[0], own[1], own[2]]) + "\n"
    snapshot = snapshot_of(
        files={"brain/adr-draft.md": draft.encode(), PLAN: plan.encode()},
        repos={"demo-api": {"docs/adr/0001.md": ("\n".join(lines[:3]) + "\n").encode()}},
    )

    edits = brain_leak_edits(snapshot)

    # The plan quotes one of the ADR's lines and is still fixed, so the ADR file was read.
    assert [edit.path for edit in edits] == [PLAN]
    assert list(BRAIN_LEAK.check(fixed(snapshot))) == []


def test_rewrites_note_when_copied_into_adr_folder(snapshot_of: SnapshotFactory) -> None:
    copied = sentence(70)
    own = [sentence(70, tag=f"own{n}") for n in range(3)]
    plan = "\n".join(["# Plan", own[0], copied, own[1], own[2]]) + "\n"
    snapshot = snapshot_of(
        files={PLAN: plan.encode()},
        repos={"demo-api": {"docs/adr/0001-x.md": f"# 1. X\n\n{copied}\n".encode()}},
    )

    (edit,) = brain_leak_edits(snapshot)

    assert edit.path == PLAN
    assert edit.text == plan.replace(copied, "[in ../demo-api/docs/adr/0001-x.md:3]")
    assert list(BRAIN_LEAK.check(fixed(snapshot))) == []


def test_rewrites_draft_when_line_copied_outside_adr_folder(snapshot_of: SnapshotFactory) -> None:
    landed, copied = sentence(70, tag="adr"), sentence(70, tag="readme")
    own = [sentence(70, tag=f"own{n}") for n in range(3)]
    draft = "\n".join(["# Draft", own[0], landed, own[1], copied, own[2]]) + "\n"
    snapshot = snapshot_of(
        files={"brain/f/adr-drafts/0001-x.md": draft.encode()},
        repos={
            "demo-api": {
                "README.md": f"{copied}\n".encode(),
                "docs/adr/0001-x.md": f"{landed}\n".encode(),
            }
        },
    )

    (edit,) = brain_leak_edits(snapshot)

    # Only the README copy is a leak: the line the ADR holds stays in the draft.
    assert edit.text == draft.replace(copied, "[in ../demo-api/README.md:1]")
    assert list(BRAIN_LEAK.check(fixed(snapshot))) == []


def test_shares_draft_rule_when_fix_reads_brain() -> None:
    # One predicate says what an ADR draft is, for the rule and for its fix alike.
    assert getattr(brain_leak_fix, "is_adr_draft", None) is brain_leak_rule.is_adr_draft
