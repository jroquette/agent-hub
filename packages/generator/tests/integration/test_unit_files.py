"""The unit reader on real folders (AGH-295, A1): a name that vanishes below a skill folder while
it is read is skipped, as the listing skips it; the unit is still read whole."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.testing.skill_trees import write_tree
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
