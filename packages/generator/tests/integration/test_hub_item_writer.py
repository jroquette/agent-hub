"""``FileSystemHubItemWriter`` when a write fails midway or the hub is read-only (AC-295.25,
AC-295.26): the unit is left as it was, with no temp, stage or old-folder leftover, and the
error names no path."""

import errno
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_files.tree_snapshot import is_leftover_name
from agent_hub.core.item_versions.hub_item_writer import HubItemWriteError, ItemWriteRefusedError
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import MAX_UNIT_FILES, UnitContent, UnitFile
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS, MAX_SKILL_FILE_BYTES
from agent_hub.core.testing.skill_trees import write_tree
from agent_hub.generator.doctor_snapshot import item_leftovers
from agent_hub.generator.hub_item_writer import FileSystemHubItemWriter
from agent_hub.generator.registered_hub_files import HubFileSystem

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
    real: Callable[..., Any], *, call: int, raised: int = errno.EIO, also: int = 0
) -> Callable[..., Any]:
    calls = [0]

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        if calls[0] in {call, also}:
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


def test_puts_hidden_entries_back_when_first_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = {**OLD_SKILL, f"{SKILL}/.cache/data": b"cached", f"{SKILL}/references/.keep": b"k"}
    hub = _hub(tmp_path, tree)
    # Two hidden entries move into the stage, then moving the old folder aside fails.
    monkeypatch.setattr(os, "rename", _failing_on(os.rename, call=3))

    with pytest.raises(HubItemWriteError) as raised:
        FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)

    assert raised.value.kind == "failed"
    assert _files(hub) == tree
    assert os.listdir(hub / SKILLS) == ["alpha"]


def test_reports_rollback_failed_when_old_folder_not_put_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, OLD_SKILL)
    # The swap fails (2nd rename), then putting the old folder back fails (3rd).
    monkeypatch.setattr(os, "rename", _failing_on(os.rename, call=2, also=3))

    with pytest.raises(HubItemWriteError) as raised:
        FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)
    monkeypatch.undo()

    assert raised.value.kind == "rollback_failed"
    assert raised.value.cause == "the old folder was not put back"
    assert "alpha" not in str(raised.value)
    assert str(hub) not in str(raised.value)
    leftovers, _ = item_leftovers(str(hub))
    assert not (hub / SKILL).exists()
    assert len(leftovers) == 2
    old = {path.removeprefix(f"{SKILL}/"): content for path, content in OLD_SKILL.items()}
    assert old in [_files(hub / leftover) for leftover in leftovers]


def test_refuses_folder_when_non_hidden_entry_deeper_than_a_unit(tmp_path: Path) -> None:
    tree = {**OLD_SKILL, f"{SKILL}/a/b/c/d": b"deep", f"{SKILL}/a/b/c/.keep": b"k"}
    hub = _hub(tmp_path, tree)

    with pytest.raises(HubItemWriteError) as raised:
        FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)

    assert raised.value.kind == "failed"
    assert _files(hub) == tree
    assert os.listdir(hub / SKILLS) == ["alpha"]


def test_carries_hidden_entry_when_below_deepest_folder(tmp_path: Path) -> None:
    hub = _hub(tmp_path, {**OLD_SKILL, f"{SKILL}/a/b/c/.keep": b"k"})

    FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)

    expected = {f"{SKILL}/{file.path}": file.content for file in NEW_SKILL.files}
    assert _files(hub) == expected | {f"{SKILL}/a/b/c/.keep": b"k"}


def test_writes_back_unit_read_when_at_each_bound(tmp_path: Path) -> None:
    # What the reader accepts at its bounds (depth, file count, file size), the writer writes.
    bundled = MAX_UNIT_FILES - 3
    tree = {
        f"{SKILL}/SKILL.md": b"# skill\n",
        f"{SKILL}/a/b/deepest.md": b"at the depth bound",
        f"{SKILL}/big.bin": b"x" * MAX_SKILL_FILE_BYTES,
        **{f"{SKILL}/many/f{number:03}.md": b"f" for number in range(bundled)},
        f"{SKILL}/a/b/c/.keep": b"hidden below the bound",
    }
    hub = _hub(tmp_path, tree)
    read = HubFileSystem().read_unit(str(hub), SKILL, kind=UnitKind.SKILL)
    assert isinstance(read, UnitContent)
    assert len(read.files) == MAX_UNIT_FILES
    (hub / SKILL / "SKILL.md").write_bytes(b"# changed\n")

    FileSystemHubItemWriter().write_unit(str(hub), SKILL, read, kind=UnitKind.SKILL)

    assert _files(hub) == tree
    assert os.listdir(hub / SKILLS) == ["alpha"]


def test_writes_back_unit_read_when_at_names_bound(tmp_path: Path) -> None:
    # SKILL.md and hidden names: exactly the names a unit read examines, read and written back.
    hidden = {f"{SKILL}/.n{number}": b"" for number in range(DEFAULT_LIMITS.names_examined - 1)}
    tree = {f"{SKILL}/SKILL.md": b"# skill\n", **hidden}
    hub = _hub(tmp_path, tree)
    read = HubFileSystem().read_unit(str(hub), SKILL, kind=UnitKind.SKILL)
    assert isinstance(read, UnitContent)
    (hub / SKILL / "SKILL.md").write_bytes(b"# changed\n")

    FileSystemHubItemWriter().write_unit(str(hub), SKILL, read, kind=UnitKind.SKILL)

    assert _files(hub) == tree
    assert os.listdir(hub / SKILLS) == ["alpha"]


def test_raises_interrupt_as_is_when_roll_back_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, OLD_SKILL)
    real = os.rename
    calls = [0]

    def rename(*args: Any, **kwargs: Any) -> None:
        calls[0] += 1
        if calls[0] == 2:
            raise KeyboardInterrupt
        if calls[0] == 3:
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        real(*args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)

    with pytest.raises(KeyboardInterrupt):
        FileSystemHubItemWriter().write_unit(str(hub), SKILL, NEW_SKILL, kind=UnitKind.SKILL)


DRAFT = ".hub-drafts/hook-abc123"


def test_refuses_draft_when_draft_holds_fifo(tmp_path: Path) -> None:
    hub = _hub(tmp_path, {f"{DRAFT}/hooks.json": b"{}"})
    os.mkfifo(hub / DRAFT / "scripts")
    os.mkfifo(hub / ".hub-drafts/hook-fifo00")

    with pytest.raises(ItemWriteRefusedError) as refused:
        FileSystemHubItemWriter().read_draft(str(hub), "hook-abc123")
    with pytest.raises(EntityNotFoundError):
        FileSystemHubItemWriter().read_draft(str(hub), "hook-fifo00")

    assert refused.value.code == "link_in_path"
    assert "hub-drafts" not in str(refused.value)


def test_reports_failure_when_draft_removal_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, {f"{DRAFT}/hooks.json": b"{}"})
    monkeypatch.setattr(os, "rename", _failing_on(os.rename, call=1))

    with pytest.raises(HubItemWriteError) as raised:
        FileSystemHubItemWriter().remove_draft(str(hub), "hook-abc123")

    assert _files(hub) == {f"{DRAFT}/hooks.json": b"{}"}
    assert "hub-drafts" not in str(raised.value)


def test_renames_draft_aside_when_removing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, {f"{DRAFT}/hooks.json": b"{}"})
    removed: list[str] = []
    real = shutil.rmtree

    def rmtree(path: str, *args: Any, **kwargs: Any) -> None:
        removed.append(path)
        real(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree)

    FileSystemHubItemWriter().remove_draft(str(hub), "hook-abc123")

    assert os.listdir(hub / ".hub-drafts") == []
    assert len(removed) == 1
    assert is_leftover_name(removed[0])


def test_reports_failure_when_draft_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, {f"{DRAFT}/hooks.json": b"{}"})
    monkeypatch.setattr(os, "read", _failing_on(os.read, call=1))

    with pytest.raises(HubItemWriteError) as raised:
        FileSystemHubItemWriter().read_draft(str(hub), "hook-abc123")

    assert "hub-drafts" not in str(raised.value)


def test_reports_failure_when_draft_name_not_utf8(tmp_path: Path) -> None:
    hub = _hub(tmp_path, {f"{DRAFT}/hooks.json": b"{}"})
    descriptor = os.open(bytes(hub / DRAFT) + b"/\xff.sh", os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(descriptor)

    with pytest.raises(HubItemWriteError):
        FileSystemHubItemWriter().read_draft(str(hub), "hook-abc123")


def test_reports_failure_when_draft_folder_cannot_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = _hub(tmp_path, {f"{DRAFT}/hooks.json": b"{}"})
    real = os.open

    def refusing(path: Any, *args: Any, **kwargs: Any) -> int:
        if path == "hook-abc123":
            raise OSError(errno.EACCES, os.strerror(errno.EACCES))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", refusing)

    with pytest.raises(HubItemWriteError) as raised:
        FileSystemHubItemWriter().read_draft(str(hub), "hook-abc123")

    assert "hub-drafts" not in str(raised.value)
