"""The brain-care pack's ``read_inbox.py`` (AGH-487), in process: the inbox notes a run reviews."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/brain-care/scripts/read_inbox.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.brain-care.scripts.read_inbox"
TODAY = "2026-10-22"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def a_note(
    hub: Path, name: str, *, provenance: str | None = "agent", status: str = "", body: str = ""
) -> str:
    inbox = hub / "brain/_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    head = ["---", "type: learning"]
    if provenance is not None:
        head.append(f"provenance: {provenance}")
    if status:
        head.append(f"status: {status}")
    title = name.removesuffix(".md")
    text = "\n".join([*head, "---", f"# {title}", "", body or f"About {title}.", ""])
    (inbox / name).write_text(text, encoding="utf-8")
    return f"brain/_inbox/{name}"


def read(hub: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    assert load().main(["--root", str(hub), "--today", TODAY]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_lists_notes_with_age_and_provenance_when_inbox_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dated = a_note(tmp_path, "2026-10-20-cache-key.md", provenance="agent-from-code")
    undated = a_note(tmp_path, "loose-note.md", provenance="human", body="Line one.\x07\nLine two.")

    found = read(tmp_path, capsys)

    assert found == {
        "count": 2,
        "notes": [
            {
                "path": dated,
                "title": "2026-10-20-cache-key",
                "age_days": 2,
                "provenance": "agent-from-code",
                "external": False,
                "excerpt": "# 2026-10-20-cache-key\n\nAbout 2026-10-20-cache-key.",
            },
            {
                "path": undated,
                "title": "loose-note",
                "age_days": None,
                "provenance": "human",
                "external": False,
                "excerpt": "# loose-note\n\nLine one.\nLine two.",
            },
        ],
        "paths": [dated, undated],
        "external": [],
        "unreadable": [],
        "omitted": 0,
    }


@pytest.mark.parametrize(
    ("provenance", "external"),
    [
        ("agent", False),
        ("agent-from-code", False),
        ("human", False),
        ("agent-from-external", True),
        ("web", True),
        (None, True),
    ],
)
def test_marks_external_when_provenance_not_agent_or_human(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    provenance: str | None,
    external: bool,
) -> None:
    path = a_note(tmp_path, "2026-10-21-a.md", provenance=provenance)

    found = read(tmp_path, capsys)

    assert found["notes"][0]["external"] is external
    assert found["external"] == ([path] if external else [])


@pytest.mark.parametrize("status", ["routed", "check", "accepted"])
def test_skips_note_when_status_not_proposed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status: str
) -> None:
    kept = a_note(tmp_path, "2026-10-21-a.md", status="proposed")
    a_note(tmp_path, "2026-10-21-b.md", status=status)

    assert read(tmp_path, capsys)["paths"] == [kept]


def test_ignores_subfolders_when_inbox_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = a_note(tmp_path, "2026-10-21-a.md")
    for folder in ("sessions", "_archive"):
        (tmp_path / "brain/_inbox" / folder).mkdir()
        (tmp_path / "brain/_inbox" / folder / "x.md").write_text("# x\n")
    (tmp_path / "brain/_inbox/.hidden.md").write_text("# hidden\n")
    (tmp_path / "brain/_inbox/notes.txt").write_text("not markdown\n")

    assert read(tmp_path, capsys)["paths"] == [kept]


def test_lists_unreadable_when_note_is_link_or_large_or_not_utf8(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = a_note(tmp_path, "2026-10-21-a.md")
    inbox = tmp_path / "brain/_inbox"
    (inbox / "2026-10-21-b.md").symlink_to(inbox / "2026-10-21-a.md")
    (inbox / "2026-10-21-c.md").write_text("x" * (256 * 1024 + 1))
    (inbox / "2026-10-21-d.md").write_bytes(b"# bad \xff\n")
    (inbox / "2026-10-21-e.md").write_text("---\n" + "k: v\n" * 65 + "---\n# e\n")

    found = read(tmp_path, capsys)

    assert found["paths"] == [kept]
    assert found["unreadable"] == [
        {"path": "brain/_inbox/2026-10-21-b.md", "reason": "a link"},
        {"path": "brain/_inbox/2026-10-21-c.md", "reason": "larger than 256 KiB"},
        {"path": "brain/_inbox/2026-10-21-d.md", "reason": "not UTF-8"},
        {"path": "brain/_inbox/2026-10-21-e.md", "reason": "front matter longer than 64 lines"},
    ]


def test_omits_notes_past_fifty_when_inbox_large(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for day in range(1, 53):
        a_note(tmp_path, f"2026-08-{day:02d}-n.md" if day <= 31 else f"2026-09-{day - 31:02d}-n.md")

    found = read(tmp_path, capsys)

    assert found["count"] == 50
    assert found["omitted"] == 2
    # Oldest first: the two newest wait for the next run.
    assert found["paths"][0] == "brain/_inbox/2026-08-01-n.md"
    assert "brain/_inbox/2026-09-21-n.md" not in found["paths"]


def test_omits_trailing_notes_when_excerpts_exceed_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for n in range(40):
        a_note(tmp_path, f"2026-09-{n + 1:02d}-n.md" if n < 30 else f"2026-10-{n - 29:02d}-n.md",
               body="界" * 3000)  # fmt: skip

    found = read(tmp_path, capsys)

    shown = json.dumps(found["notes"], ensure_ascii=False).encode()
    assert len(shown) <= 96 * 1024
    assert all(len(note["excerpt"]) <= 1500 for note in found["notes"])
    assert found["count"] + found["omitted"] == 40
    assert found["omitted"] > 0
    assert found["paths"][0] == "brain/_inbox/2026-09-01-n.md"


def test_lists_nothing_when_hub_has_no_inbox(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    found = read(tmp_path, capsys)

    assert (found["count"], found["notes"], found["omitted"]) == (0, [], 0)


@pytest.mark.parametrize("argv", [["--today", "22/10/2026"], ["--root", "missing"]])
def test_exits_two_when_today_or_root_invalid(tmp_path: Path, argv: list[str]) -> None:
    given = ["--root", str(tmp_path), *argv]
    if "missing" in argv:
        given = ["--root", str(tmp_path / "missing")]

    assert load().main(given) == 2
