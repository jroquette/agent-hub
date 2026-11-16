"""The core contract suites run here against the generator's file system adapter."""

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_hub.core.item_versions.hub_item_writer import HubItemWriter
from agent_hub.core.testing.hub_item_writer_contract import WriterTree
from agent_hub.core.testing.skill_sources_contract import SkillTree
from agent_hub.core.testing.skill_trees import DiskSkillTree, Link, write_tree
from agent_hub.generator.hub_item_writer import FileSystemHubItemWriter
from agent_hub.generator.registered_hub_files import HubFileSystem

# The shared conftest's ``read_only_tree``: makes every folder under a root unwritable.
type ReadOnlyMaker = Callable[[Path], None]


@pytest.fixture
def skill_tree(tmp_path: Path) -> SkillTree:
    hub = tmp_path / "hub"
    hub.mkdir()
    return DiskSkillTree(root=hub, reader=HubFileSystem())


@dataclass
class DiskWriterTree:
    """The ``writer_tree`` fixture of the file system writer: a hub folder at ``root``."""

    root: Path
    writer: HubItemWriter
    read_only: ReadOnlyMaker

    @property
    def hub_path(self) -> str:
        """The hub folder."""
        return str(self.root)

    def write(self, path: str, content: bytes) -> None:
        """Write a regular file."""
        write_tree(self.root, {path: content})

    def link(self, path: str, target: str) -> None:
        """Make a link to ``target``."""
        write_tree(self.root, {path: Link(target)})

    def make_folder(self, path: str) -> None:
        """Make an empty folder and its parents."""
        (self.root / path).mkdir(parents=True, exist_ok=True)

    def make_executable(self, path: str) -> None:
        """Set the owner's, group's and others' executable bits."""
        target = self.root / path
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def make_read_only(self) -> None:
        """Make every folder of the hub unwritable."""
        self.read_only(self.root)

    def files(self, below: str) -> dict[str, bytes]:
        """The regular files under ``below``, links not followed."""
        base = self.root / below
        found: dict[str, bytes] = {}
        for top, _, names in os.walk(base):
            for name in names:
                path = Path(top) / name
                if path.is_file() and not path.is_symlink():
                    found[path.relative_to(base).as_posix()] = path.read_bytes()
        return found

    def is_executable(self, path: str) -> bool:
        """Whether the owner's executable bit is set."""
        return bool((self.root / path).stat().st_mode & stat.S_IXUSR)

    def exists(self, path: str) -> bool:
        """Whether an entry is at ``path``, a link not followed."""
        return (self.root / path).is_symlink() or (self.root / path).exists()

    def names(self, folder: str) -> set[str]:
        """The names in ``folder``; none when it is absent."""
        base = self.root / folder
        return set(os.listdir(base)) if base.is_dir() else set()


@pytest.fixture
def writer_tree(tmp_path: Path, read_only_tree: ReadOnlyMaker) -> WriterTree:
    hub = tmp_path / "hub"
    hub.mkdir()
    return DiskWriterTree(root=hub, writer=FileSystemHubItemWriter(), read_only=read_only_tree)
