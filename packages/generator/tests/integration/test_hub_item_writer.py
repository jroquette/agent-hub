"""``FileSystemHubItemWriter`` when a write fails midway or the hub is read-only (AC-295.25,
AC-295.26): the unit is left as it was, with no temp, stage or old-folder leftover, and the
error names no path."""

import errno
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.item_versions.hub_item_writer import HubItemWriteError, ItemWriteRefusedError
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.testing.skill_trees import write_tree
from agent_hub.generator.hub_item_writer import FileSystemHubItemWriter

SKILLS = "plugin/demo/skills"
SKILL = f"{SKILLS}/alpha"
AGENT = ".claude/agents/reviewer.md"
OLD_SKILL = {f"{SKILL}/SKILL.md": b"# old\n", f"{SKILL}/references/r.md": b"# old r\n"}
NEW_SKILL = UnitContent(
    files=(
        UnitFile(path="SKILL.md", content=b"# new\n"),
        UnitFile(path="scripts/s.sh", content=b"#!/bin/sh\n", executable=True),
    )
)


def _files(root: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for top, _, names in os.walk(root):
        for name in names:
            path = Path(top) / name
            if not path.is_symlink():
                found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def _failing_on(
    real: Callable[..., Any], *, call: int, raised: int = errno.EIO
) -> Callable[..., Any]:
    calls = [0]

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        if calls[0] == call:
            raise OSError(raised, os.strerror(raised))
        return real(*args, **kwargs)

    return wrapped


def _hub(tmp_path: Path, tree: dict[str, bytes]) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir()
    write_tree(hub, tree)
    return hub


def test_keeps_old_folder_when_swap_fails_midway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, OLD_SKILL)
    # The first rename moves the old folder aside, the second puts the stage in place.
    monkeypatch.setattr(os, "rename", _failing_on(os.rename, call=2))

    with pytest.raises(HubItemWriteError) as raised:
        FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)

    assert _files(hub) == OLD_SKILL
    assert os.listdir(hub / SKILLS) == ["alpha"]
    assert str(hub) not in str(raised.value)
    assert "alpha" not in str(raised.value)


def test_puts_hidden_entries_back_when_swap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = {**OLD_SKILL, f"{SKILL}/.cache/data": b"cached", f"{SKILL}/references/.keep": b"k"}
    hub = _hub(tmp_path, tree)
    # Two hidden entries move into the stage, the old folder moves aside, then the swap fails.
    monkeypatch.setattr(os, "rename", _failing_on(os.rename, call=4))

    with pytest.raises(HubItemWriteError):
        FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)

    assert _files(hub) == tree
    assert os.listdir(hub / SKILLS) == ["alpha"]


def test_removes_stage_when_staged_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, OLD_SKILL)
    monkeypatch.setattr(os, "fchmod", _failing_on(os.fchmod, call=2))

    with pytest.raises(HubItemWriteError):
        FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)

    assert _files(hub) == OLD_SKILL
    assert os.listdir(hub / SKILLS) == ["alpha"]


def test_leaves_no_temp_when_file_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, {AGENT: b"old\n"})
    monkeypatch.setattr(os, "replace", _failing_on(os.replace, call=1))
    new = UnitContent(files=(UnitFile(path="reviewer.md", content=b"new\n"),))

    with pytest.raises(HubItemWriteError) as raised:
        FileSystemHubItemWriter().write_unit(str(hub), AGENT, new, kind=UnitKind.AGENT)

    assert _files(hub) == {AGENT: b"old\n"}
    assert os.listdir(hub / ".claude/agents") == ["reviewer.md"]
    assert "reviewer" not in str(raised.value)


def test_reports_read_only_when_hub_not_writable(
    tmp_path: Path, read_only_tree: Callable[[Path], None]
) -> None:
    hub = _hub(tmp_path, {**OLD_SKILL, AGENT: b"old\n"})
    read_only_tree(hub)
    writer = FileSystemHubItemWriter()
    new = UnitContent(files=(UnitFile(path="reviewer.md", content=b"new\n"),))

    assert not writer.is_writable(str(hub), [SKILL, AGENT])
    with pytest.raises(ItemWriteRefusedError) as folder:
        writer.write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)
    with pytest.raises(ItemWriteRefusedError) as file:
        writer.write_unit(str(hub), AGENT, new, kind=UnitKind.AGENT)

    assert (folder.value.code, file.value.code) == ("hub_read_only", "hub_read_only")
    assert _files(hub) == {**OLD_SKILL, AGENT: b"old\n"}


def test_reports_read_only_when_mount_refuses_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, OLD_SKILL)
    monkeypatch.setattr(os, "mkdir", _failing_on(os.mkdir, call=1, raised=errno.EROFS))

    with pytest.raises(ItemWriteRefusedError) as raised:
        FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)

    assert raised.value.code == "hub_read_only"
    assert _files(hub) == OLD_SKILL
