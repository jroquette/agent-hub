"""``/projects/{project}/brain`` and ``/brain/note`` on the composed app over a registered hub
(AC-201.33, AC-201.34): the tree lists the brain's ``.md`` notes without ``auto/``; a note is
read on request; a path that leaves ``brain/``, a link, a personal note or an oversized note is
a 400, 404 or 413 problem that serves nothing from outside the brain."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

AUTO_SENTINEL = "AUTO-m3k7-personal-never-served"
OUTSIDE_SENTINEL = "OUTSIDE-z5c1-never-served"
DECISIONS = """---
type: decisions
last_verified: 2026-10-01
---
# Decisions

- D1 keep the brain small.
"""
NOTE_LIMIT = 256 * 1024
BRAIN = "/api/v1/projects/demo/brain"
NOTE = f"{BRAIN}/note"


@pytest.fixture
def brain_hub(composed: Any, make_hub: Callable[..., Path]) -> Path:
    hub = make_hub()
    brain = hub / "brain"
    (brain / "decisions" / "index.md").write_text(DECISIONS, encoding="utf-8")
    (brain / "playbooks" / "release").mkdir(parents=True)
    (brain / "playbooks" / "release" / "steps.md").write_text("# Steps\n", encoding="utf-8")
    (brain / "playbooks" / "notes.txt").write_text("not a note\n", encoding="utf-8")
    (brain / "auto" / "workspace" / "me.md").write_text(f"# Me\n\n{AUTO_SENTINEL}\n")
    (brain / "large.md").write_text("# Large\n\n" + "x" * (300 * 1024) + "\n")
    outside = hub / "outside.md"
    outside.write_text(f"# Outside\n\n{OUTSIDE_SENTINEL}\n", encoding="utf-8")
    (brain / "linked.md").symlink_to(outside)
    (brain / "linked-dir").symlink_to(hub, target_is_directory=True)
    registered = composed.client.post("/api/v1/hubs", json={"path": str(hub)})
    assert registered.status_code == 201, registered.text
    return hub


def test_reads_tree_and_note_when_brain_nested(composed: Any, brain_hub: Path) -> None:
    tree = composed.client.get(BRAIN)
    note = composed.client.get(NOTE, params={"path": "decisions/index.md"})

    assert tree.status_code == 200, tree.text
    paths = {entry["path"] for entry in tree.json()["entries"]}
    assert {"index.md", "now.md", "decisions/index.md", "playbooks/release/steps.md"} <= paths
    assert all(path.endswith(".md") for path in paths)
    assert not [path for path in paths if path.startswith(("auto/", "linked"))]
    assert tree.json()["project"] == "demo"
    assert note.status_code == 200, note.text
    body = note.json()
    assert body["frontmatter"] == {"type": "decisions", "last_verified": "2026-10-01"}
    assert body["markdown"] == "# Decisions\n\n- D1 keep the brain small.\n"
    assert body["size"] == len(DECISIONS.encode())
    assert (body["project"], body["path"]) == ("demo", "decisions/index.md")
    assert AUTO_SENTINEL not in tree.text


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Path]]:
    """Every path ``os.open`` is asked for while the test runs, resolved against its ``dir_fd``
    (Linux ``/proc``), without following a final link."""
    seen: list[Path] = []
    real_open = os.open

    def spy(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        base = Path(os.readlink(f"/proc/self/fd/{dir_fd}")) if dir_fd is not None else Path()
        seen.append(base / os.fsdecode(path))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", spy)
    yield seen


@pytest.mark.parametrize(
    ("query", "status"),
    [
        ("path=../hub.json", 400),
        ("path=/etc/passwd", 400),
        ("path=%2e%2e/x.md", 400),
        ("path=decisions/../../hub.json", 400),
        ("path=x.txt", 400),
        ("path=playbooks/notes.txt", 400),
        ("path=linked.md", 404),
        ("path=linked-dir/hub.json", 400),
        ("path=linked-dir/brain/index.md", 404),
        ("path=auto/workspace/me.md", 404),
        ("path=missing.md", 404),
        ("path=decisions", 400),
        ("path=large.md", 413),
    ],
)
def test_rejects_note_when_path_unsafe_or_note_unservable(
    composed: Any, brain_hub: Path, *, opened: list[Path], query: str, status: int
) -> None:
    response = composed.client.get(f"{NOTE}?{query}")

    brain = brain_hub / "brain"
    if status == 400:
        assert opened == []
    # The project lookup reads the registry and the hub's config; every other hub file opened
    # is under brain/.
    config = {brain_hub / name for name in ("hub.json", "hub.local.json", "hub.lock")}
    for path in [path for path in opened if path.is_relative_to(brain_hub)]:
        assert path in {brain_hub, brain} | config or path.is_relative_to(brain), path
        assert not path.is_relative_to(brain / "auto"), path
        assert path.name not in {"outside.md", "passwd"}, path

    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert OUTSIDE_SENTINEL not in response.text
    assert AUTO_SENTINEL not in response.text
    assert "D1 keep" not in response.text


def test_answers_not_found_when_project_unknown(composed: Any, brain_hub: Path) -> None:
    tree = composed.client.get("/api/v1/projects/nope/brain")
    note = composed.client.get("/api/v1/projects/nope/brain/note", params={"path": "index.md"})

    assert (tree.status_code, note.status_code) == (404, 404)
