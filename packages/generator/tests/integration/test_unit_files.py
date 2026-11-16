"""The unit reader on real folders (AGH-295, A1): a name that vanishes below a skill folder while
it is read is skipped, as the listing skips it; the unit is still read whole. A folder the walk
already refuses (too many files, a special or too-large file) is refused before any byte is read."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hubs.hub_registry import UnreadUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import MAX_UNIT_FILES, UnitContent, UnitFile
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES
from agent_hub.core.testing.skill_trees import Fifo, TreeEntry, write_tree
from agent_hub.generator.unit_files import read_unit

UNIT = "plugin/hub-workflow/skills/alpha"
SKILL = b"# Alpha\n"
KEPT = b"# Kept\n"


def _vanish_on(
    monkeypatch: pytest.MonkeyPatch, *, call: str, name: str, nth: int, vanish: Callable[[], None]
) -> None:
    """Run ``vanish`` just before the ``nth`` ``os.<call>`` of ``name``, then call through."""
    real = getattr(os, call)
    seen = [0]

    def spy(path: Any, *args: Any, **kwargs: Any) -> Any:
        if path == name:
            seen[0] += 1
            if seen[0] == nth:
                vanish()
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, call, spy)


@pytest.mark.parametrize(
    "case",
    [
        ("stat", "gone.md", 1),
        ("stat", "gone.md", 2),
        ("open", "gone.md", 1),
        ("stat", "old", 1),
        ("open", "old", 1),
        ("open", "old", 2),
    ],
)
def test_skips_name_when_it_vanishes_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: tuple[str, str, int]
) -> None:
    call, name, nth = case
    hub = tmp_path / "hub"
    write_tree(
        hub,
        {
            f"{UNIT}/SKILL.md": SKILL,
            f"{UNIT}/references/gone.md": b"# Gone\n",
            f"{UNIT}/references/kept.md": KEPT,
            f"{UNIT}/old/x.md": b"# Old\n",
        },
    )
    target = hub / UNIT / ("references/gone.md" if name == "gone.md" else "old")

    def vanish() -> None:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    _vanish_on(monkeypatch, call=call, name=name, nth=nth, vanish=vanish)

    read = read_unit(hub, UNIT, kind=UnitKind.SKILL)

    kept = {"SKILL.md": SKILL, "references/kept.md": KEPT}
    if name == "gone.md":
        kept["old/x.md"] = b"# Old\n"
    else:
        kept["references/gone.md"] = b"# Gone\n"
    expected = UnitContent(
        files=tuple(UnitFile(path=path, content=content) for path, content in sorted(kept.items()))
    )
    assert read == expected


def _counting_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Every byte count ``os.read`` answers while the test runs (each file's content is read
    through it, so a refusal that reads nothing leaves the list empty)."""
    counted: list[int] = []
    real = os.read

    def spy(descriptor: int, length: int) -> bytes:
        chunk = real(descriptor, length)
        counted.append(len(chunk))
        return chunk

    monkeypatch.setattr(os, "read", spy)
    return counted


@pytest.mark.parametrize("problem", ["too_many_files", "special_file", "file_too_large"])
def test_reads_no_bytes_when_folder_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    hub = tmp_path / "hub"
    tree: dict[str, TreeEntry] = {f"{UNIT}/SKILL.md": SKILL}
    if problem == "too_many_files":
        tree |= {f"{UNIT}/r/{index:03d}.md": b"# R\n" for index in range(MAX_UNIT_FILES)}
    else:
        # Earlier files in path order, then the refused one last.
        tree |= {f"{UNIT}/a/{index}.md": b"# A\n" for index in range(5)}
        tree[f"{UNIT}/z/last"] = (
            Fifo() if problem == "special_file" else b"x" * (MAX_SKILL_FILE_BYTES + 1)
        )
    write_tree(hub, tree)
    counted = _counting_reads(monkeypatch)

    read = read_unit(hub, UNIT, kind=UnitKind.SKILL)

    expected = "unreadable" if problem == "special_file" else "too_large"
    assert read == UnreadUnit(kind=expected)
    assert sum(counted) == 0
