"""The control plane's ``HubFileReader``: a registered hub's files, read as ``hub doctor`` does.

``hub.json`` and ``hub.local.json`` go through ``hub_config_files``, the lock and the doctor
snapshot through ``doctor_snapshot``, feature folders through ``feature_files``, brain notes
through ``brain_files``, skills, agents and hooks through ``skill_files``. The hub's
``hub.local.json`` is the one in the registered folder (``hub doctor`` reads the main
checkout's, the same folder for a hub registered at its main checkout). The developer's branch
prefix comes from the files alone unless ``read_git`` is given: git stays with the composition
root, which may pass a reader of ``git config`` in the hub.
"""

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from agent_hub.core.doctor.run_rules import Selection
from agent_hub.core.doctor.snapshot import DoctorSnapshot, LockState, lines_of
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.hub_config.effective_identity import (
    GitReader,
    IdentityValues,
    Sourced,
    resolve_branch_prefix,
)
from agent_hub.core.hub_config.local_config import LOCAL_FILE, LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hubs.hub_registry import BrainListing, UnreadHubFile
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS, SkillLimits, SkillSources
from agent_hub.generator.brain_files import (
    brain_file_size,
    brain_folders,
    list_brain,
    read_brain_file,
)
from agent_hub.generator.doctor_snapshot import build_doctor_snapshot, read_lock
from agent_hub.generator.feature_files import read_feature_folder, read_feature_folders
from agent_hub.generator.hub_config_files import UnreadFile, read_file_bytes, read_local_json
from agent_hub.generator.skill_files import list_skill_sources, read_skill_file

HUB_JSON: Final = "hub.json"
NOW_PATH: Final = ("brain", "now.md")
AGENTS_MD: Final = "AGENTS.md"
# ``brain/now.md`` and a repo's ``AGENTS.md`` are read up to this size.
MAX_NOTE_BYTES: Final = 1_048_576
# The server reads every registered hub's hub.json; a larger one is reported, not read.
MAX_HUB_JSON_BYTES: Final = 1_048_576

# Makes the git reader for one hub folder.
type GitReaderFactory = Callable[[str], GitReader]


def _no_git(_keys: frozenset[str]) -> Mapping[str, str]:
    return {}


def _files_only(_hub_path: str) -> GitReader:
    return _no_git


class HubFileSystem:
    """Reads registered hubs from the file system."""

    def __init__(self, *, read_git: GitReaderFactory = _files_only) -> None:
        self._read_git = read_git

    def resolve(self, path: str) -> str:
        """The absolute real path of ``path`` (``~`` expanded)."""
        return os.path.realpath(os.path.expanduser(path))

    def read_hub_json(self, hub_path: str) -> bytes | UnreadHubFile:
        """The bytes of ``hub.json`` as read (at most ``MAX_HUB_JSON_BYTES``), or why not."""
        return _unread_or_bytes(
            read_file_bytes(Path(hub_path, HUB_JSON), max_bytes=MAX_HUB_JSON_BYTES)
        )

    def read_lock(self, hub_path: str) -> LockState | None:
        """``hub.lock`` as found, never through a link; None when it cannot be read."""
        return read_lock(hub_path)

    def read_local(self, hub_path: str) -> LocalConfig | tuple[ConfigProblem, ...]:
        """The hub's ``hub.local.json``."""
        return read_local_json(Path(hub_path, LOCAL_FILE))

    def doctor_snapshot(
        self,
        hub_path: str,
        *,
        config: HubConfig,
        running_version: str,
        selection: Selection,
        local: LocalConfig | tuple[ConfigProblem, ...],
    ) -> DoctorSnapshot:
        """What the selected rules read of the hub."""

        def branch_prefix() -> Sourced | None:
            if not isinstance(local, LocalConfig):
                return None
            return resolve_branch_prefix(
                local=IdentityValues.of(local.project),
                hub=IdentityValues.of(config.project),
                read_git=self._read_git(hub_path),
            )

        return build_doctor_snapshot(
            hub_path,
            config=config,
            running=running_version,
            selection=selection,
            local=local,
            branch_prefix=branch_prefix,
        )

    def modified_times(self, hub_path: str, paths: Sequence[str]) -> tuple[int | None, ...]:
        """Each path's modification time in ns, looked at without following a link."""
        return tuple(_modified(Path(hub_path, path)) for path in paths)

    def read_now(self, hub_path: str) -> bytes | UnreadHubFile:
        """The bytes of ``brain/now.md``, or why not."""
        return _unread_or_bytes(
            read_file_bytes(Path(hub_path, *NOW_PATH), max_bytes=MAX_NOTE_BYTES)
        )

    def agents_md_lines(self, hub_path: str, repo_dir: str) -> int | None:
        """The line count of ``../<repo_dir>/AGENTS.md``; None when absent or unreadable."""
        checkout = os.path.realpath(os.path.join(hub_path, os.pardir, repo_dir))
        read = read_file_bytes(Path(checkout, AGENTS_MD), max_bytes=MAX_NOTE_BYTES)
        if isinstance(read, UnreadFile):
            return None
        return len(lines_of(read.decode("utf-8", "replace")))

    def feature_folders(self, hub_path: str) -> tuple[FeatureFolder, ...]:
        """The hub's feature folders."""
        return read_feature_folders(Path(hub_path))

    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        """The hub's feature folder ``slug``; None when there is no such folder."""
        return read_feature_folder(Path(hub_path), slug)

    def brain_tree(self, hub_path: str) -> BrainListing:
        """The ``.md`` notes under the hub's ``brain/``, bounded, no link followed."""
        return list_brain(Path(hub_path))

    def brain_folders(self, hub_path: str) -> tuple[str, ...]:
        """The top-level folders of the hub's ``brain/``, bounded, no link followed."""
        return brain_folders(Path(hub_path))

    def read_brain_file(self, hub_path: str, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
        """The bytes of ``brain/<path>``, a regular file of at most ``max_bytes``, or why not."""
        return read_brain_file(Path(hub_path), path, max_bytes=max_bytes)

    def brain_file_size(self, hub_path: str, path: str) -> int | None:
        """The size of the regular file ``brain/<path>``; None when absent, a link or unreadable."""
        return brain_file_size(Path(hub_path), path)

    def skill_sources(self, hub_path: str, *, limits: SkillLimits = DEFAULT_LIMITS) -> SkillSources:
        """Every entry under the hub's skill roots, stat-only, bounded, no link followed."""
        return list_skill_sources(Path(hub_path), limits)

    def read_skill_file(self, hub_path: str, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
        """The bytes of the hub-relative ``path`` under the skill roots, or why not."""
        return read_skill_file(Path(hub_path), path, max_bytes=max_bytes)


def _unread_or_bytes(read: bytes | UnreadFile) -> bytes | UnreadHubFile:
    if isinstance(read, UnreadFile):
        return UnreadHubFile(message=read.problem.message, is_missing=read.is_missing)
    return read


def _modified(path: Path) -> int | None:
    try:
        return os.stat(path, follow_symlinks=False).st_mtime_ns
    except OSError:
        return None
