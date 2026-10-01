"""``brain.leak``: a brain line found in a repo file (spec AC-11.28, Q-17).

Brain side: the listed UTF-8 files under the hub's ``brain/``, trimmed, outside frontmatter,
fenced blocks and table rows, of ``min_line_length`` (default 60) or more characters. Repo side:
every listed UTF-8 text file of each checkout. Every text here is synthetic (AGENTS.md rule 4).
Scale: the brain lines are indexed once and each file is split once, checked by counting.
"""

from collections.abc import Callable
from typing import Any

import pytest

from agent_hub.core.doctor import brain_leak_rule
from agent_hub.core.doctor.brain_leak_rule import BRAIN_LEAK
from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, int | None, str]

FIX = "reword or remove the line here, or reword the brain note if it quotes this file"
NOTE = "brain/notes/widgets.md"
_FILLER = "Synthetic note: the widget queue drains before the gear spins up again and again"


def sentence(length: int, *, tag: str = "a") -> str:
    """A synthetic line of exactly ``length`` characters, no blank at either end."""
    text = (f"{tag} {_FILLER} " * (length // len(_FILLER) + 2))[:length]
    return text[:-1] + "." if text.endswith(" ") else text


def in_brain(path: str, line: int) -> str:
    return f"line also in the brain at {path}:{line}"


def leaks(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(BRAIN_LEAK.check(snapshot))
    assert all(finding.rule == "brain.leak" for finding in found)
    assert all(finding.severity is Severity.ERROR for finding in found)
    assert all(finding.fix == FIX for finding in found)
    return [(finding.path, finding.line, finding.message) for finding in found]


def a_config(**settings: Any) -> HubConfig:
    document = a_hub_document()
    document["doctor"] = {"rules": {"brain.leak": settings}}
    return HubConfig.model_validate(document)


def test_declares_design_id_when_rule_read() -> None:
    assert BRAIN_LEAK.id == "brain.leak"
    assert BRAIN_LEAK.reads == frozenset({Read.HUB_LISTING, Read.REPOS})
    assert BRAIN_LEAK.severity is Severity.ERROR
    assert BRAIN_LEAK.module is None


def test_reports_repo_line_when_brain_line_copied(snapshot_of: SnapshotFactory) -> None:
    copied, other = sentence(70), sentence(70, tag="b")
    snapshot = snapshot_of(
        files={NOTE: f"# Widgets\n\n{copied}\n{other}\n".encode()},
        repos={
            "demo-api": {
                "README.md": f"# Api\n\n{copied}\n".encode(),
                "src/app.py": f"# {other}\n{other}\n".encode(),
            },
            "demo-web": {"docs/a.md": f"intro\n{copied}\n".encode()},
        },
    )

    # The repo's path:line, shown from the hub; "# <line>" is another line once trimmed.
    assert leaks(snapshot) == [
        ("../demo-api/README.md", 3, in_brain(NOTE, 3)),
        ("../demo-api/src/app.py", 2, in_brain(NOTE, 4)),
        ("../demo-web/docs/a.md", 2, in_brain(NOTE, 3)),
    ]


def test_names_first_brain_line_when_line_repeated(snapshot_of: SnapshotFactory) -> None:
    line = sentence(64)
    snapshot = snapshot_of(
        files={"brain/b.md": f"{line}\n".encode(), "brain/a.md": f"x\n{line}\n".encode()},
        repos={"demo-api": {"README.md": f"{line}\n{line}\n".encode()}},
    )

    assert leaks(snapshot) == [
        ("../demo-api/README.md", 1, in_brain("brain/a.md", 2)),
        ("../demo-api/README.md", 2, in_brain("brain/a.md", 2)),
    ]


def test_ignores_line_when_fifty_nine_characters(snapshot_of: SnapshotFactory) -> None:
    short, long = sentence(59), sentence(60, tag="b")
    snapshot = snapshot_of(
        files={NOTE: f"{short}\n{long}\n".encode()},
        repos={"demo-api": {"README.md": f"{short}\n{long}\n".encode()}},
    )

    assert leaks(snapshot) == [("../demo-api/README.md", 2, in_brain(NOTE, 2))]


def test_ignores_line_when_only_in_hub(snapshot_of: SnapshotFactory) -> None:
    line = sentence(80)
    snapshot = snapshot_of(
        files={NOTE: f"{line}\n".encode(), "docs/guide.md": f"{line}\n".encode()},
        repos={"demo-api": {"README.md": b"# Api\n"}},
    )

    assert leaks(snapshot) == []


def test_reads_only_brain_folder_when_hub_listed(snapshot_of: SnapshotFactory) -> None:
    line = sentence(80)
    snapshot = snapshot_of(
        files={"brainstorm/n.md": f"{line}\n".encode(), "x/brain/n.md": f"{line}\n".encode()},
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert leaks(snapshot) == []


def test_reads_listed_brain_files_when_hub_listed(snapshot_of: SnapshotFactory) -> None:
    line = sentence(80)
    snapshot = snapshot_of(
        files={NOTE: f"{line}\n".encode()},
        listed=(),
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert leaks(snapshot) == []


@pytest.mark.parametrize(
    "prefix",
    [pytest.param(b"\x00", id="nul"), pytest.param(b"\xff", id="not-utf8")],
)
def test_skips_repo_file_when_binary(snapshot_of: SnapshotFactory, prefix: bytes) -> None:
    line = sentence(70)
    snapshot = snapshot_of(
        files={NOTE: f"{line}\n".encode()},
        repos={
            "demo-api": {
                "img.bin": prefix + f"\n{line}\n".encode(),
                "README.md": f"{line}\n".encode(),
            }
        },
    )

    assert leaks(snapshot) == [("../demo-api/README.md", 1, in_brain(NOTE, 1))]


@pytest.mark.parametrize(
    "prefix",
    [pytest.param(b"\x00", id="nul"), pytest.param(b"\xff", id="not-utf8")],
)
def test_skips_brain_file_when_binary(snapshot_of: SnapshotFactory, prefix: bytes) -> None:
    line = sentence(70)
    snapshot = snapshot_of(
        files={NOTE: prefix + f"\n{line}\n".encode()},
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert leaks(snapshot) == []


def test_skips_link_when_brain_or_repo_path_is_link(snapshot_of: SnapshotFactory) -> None:
    line = sentence(70)
    snapshot = snapshot_of(
        files={"docs/n.md": f"{line}\n".encode()},
        links={NOTE: "../docs/n.md"},
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert leaks(snapshot) == []


def test_skips_repo_when_checkout_missing(snapshot_of: SnapshotFactory) -> None:
    line = sentence(70)
    snapshot = snapshot_of(
        files={NOTE: f"{line}\n".encode()},
        repos={"demo-api": None, "demo-web": {"README.md": f"{line}\n".encode()}},
    )

    assert leaks(snapshot) == [("../demo-web/README.md", 1, in_brain(NOTE, 1))]


@pytest.mark.parametrize(("length", "found"), [(79, False), (80, True)])
def test_raises_bar_when_min_line_length_set(
    snapshot_of: SnapshotFactory, length: int, *, found: bool
) -> None:
    line = sentence(length)
    snapshot = snapshot_of(
        files={NOTE: f"{line}\n".encode()},
        config=a_config(min_line_length=80),
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert leaks(snapshot) == ([("../demo-api/README.md", 1, in_brain(NOTE, 1))] if found else [])


def test_lowers_bar_when_min_line_length_set(snapshot_of: SnapshotFactory) -> None:
    line = sentence(20)
    snapshot = snapshot_of(
        files={NOTE: f"{line}\n".encode()},
        config=a_config(min_line_length=20),
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert leaks(snapshot) == [("../demo-api/README.md", 1, in_brain(NOTE, 1))]


def test_skips_frontmatter_fence_and_table_when_brain_read(snapshot_of: SnapshotFactory) -> None:
    field, fenced, tilde, row, kept = (sentence(70, tag=tag) for tag in "abcde")
    table = f"| {row} |"
    note = (
        f"---\ntitle: {field}\n{field}\n---\n"
        f"```text\n{fenced}\n```\n"
        f"  ~~~~\n{tilde}\n```\nstill fenced\n  ~~~~\n"
        f"{table}\n"
        f"{kept}\n"
    )
    repo = "\n".join((field, f"title: {field}", fenced, tilde, table, kept)) + "\n"
    snapshot = snapshot_of(
        files={NOTE: note.encode()}, repos={"demo-api": {"README.md": repo.encode()}}
    )

    assert leaks(snapshot) == [("../demo-api/README.md", 6, in_brain(NOTE, 14))]


def test_reads_fence_to_end_when_never_closed(snapshot_of: SnapshotFactory) -> None:
    line = sentence(70)
    snapshot = snapshot_of(
        files={NOTE: f"```\n{line}\n".encode()},
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    assert leaks(snapshot) == []


def test_reads_lines_when_frontmatter_unterminated(snapshot_of: SnapshotFactory) -> None:
    open_only, later = sentence(70), sentence(70, tag="b")
    snapshot = snapshot_of(
        files={
            NOTE: f"---\n{open_only}\n".encode(),
            "brain/b.md": f"x\n---\n{later}\n---\n".encode(),
        },
        repos={"demo-api": {"README.md": f"{open_only}\n{later}\n".encode()}},
    )

    # Only a first line ``---`` opens frontmatter; one never closed is no frontmatter.
    assert leaks(snapshot) == [
        ("../demo-api/README.md", 1, in_brain(NOTE, 2)),
        ("../demo-api/README.md", 2, in_brain("brain/b.md", 3)),
    ]


def test_trims_line_when_indented(snapshot_of: SnapshotFactory) -> None:
    line = sentence(60)
    spaced = line.replace(" ", "  ", 1)
    wider = line.replace(" ", "   ", 1)
    snapshot = snapshot_of(
        files={NOTE: f"   {line}\t\r\n{spaced}\n".encode()},
        repos={"demo-api": {"src/a.py": f"\t\t{line}  \r\n    {spaced}\n{wider}\n".encode()}},
    )

    # Blanks at either end are cut; blanks inside are kept, so a third blank is another line.
    assert leaks(snapshot) == [
        ("../demo-api/src/a.py", 1, in_brain(NOTE, 1)),
        ("../demo-api/src/a.py", 2, in_brain(NOTE, 2)),
    ]


def test_counts_trimmed_length_when_line_padded(snapshot_of: SnapshotFactory) -> None:
    line = sentence(59)
    snapshot = snapshot_of(
        files={NOTE: f"      {line}      \n".encode()},
        repos={"demo-api": {"README.md": f"      {line}      \n".encode()}},
    )

    assert leaks(snapshot) == []


def test_cuts_brain_path_when_echoed(snapshot_of: SnapshotFactory) -> None:
    line = sentence(70)
    path = "brain/" + "n" * 500 + ".md"
    snapshot = snapshot_of(
        files={path: f"{line}\n".encode()},
        repos={"demo-api": {"README.md": f"{line}\n".encode()}},
    )

    ((_, _, message),) = leaks(snapshot)
    assert line not in message
    assert len(message) < 300
    assert message.endswith("…:1")


def test_indexes_brain_once_when_many_repos_read(
    snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scale: the brain is indexed once and each file split once, never brain × repo lines."""
    split: list[int] = []
    real_text_lines = brain_leak_rule.text_lines

    def counted(text: str) -> tuple[str, ...]:
        lines = real_text_lines(text)
        split.append(len(lines))
        return lines

    monkeypatch.setattr(brain_leak_rule, "text_lines", counted)
    lines = [sentence(70, tag=f"t{index}") for index in range(200)]
    body = "\n".join(lines) + "\n"
    snapshot = snapshot_of(
        files={NOTE: body.encode(), "brain/other.md": body.encode()},
        repos={
            repo: {f"f{index}.md": body.encode() for index in range(5)}
            for repo in ("demo-api", "demo-web", "demo-cli")
        },
    )

    found = leaks(snapshot)

    assert len(found) == 3 * 5 * 200
    assert split == [200] * (2 + 3 * 5)


def test_reads_huge_line_when_repo_file_has_one(snapshot_of: SnapshotFactory) -> None:
    line = sentence(70)
    huge = "w" * 2_000_000
    snapshot = snapshot_of(
        files={NOTE: f"{line}\n{huge}\n".encode()},
        repos={"demo-api": {"big.txt": f"{huge}\n{line}\n{huge}x\n".encode()}},
    )

    assert leaks(snapshot) == [
        ("../demo-api/big.txt", 1, in_brain(NOTE, 2)),
        ("../demo-api/big.txt", 2, in_brain(NOTE, 1)),
    ]
