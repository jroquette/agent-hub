"""Build what ``hub doctor`` knows of a valid hub: the lock, the files, the base hooks block, the
repo checkouts and the developer's branch prefix the selected rules read.

``hub doctor`` and the control plane's Health read share it, so both report the same findings.
The files are the fixed paths, the lock's managed paths when a rule reads them, and the listing
when one needs it or a file set that comes from it, read without following links (git runs only
when a rule reads the listing). Each repo checkout is ``../<dir>`` (its real path, taken once;
inside it nothing is followed). The branch prefix needs git in the developer's main checkout,
which stays with the caller: it passes ``branch_prefix``, called only when a rule reads the
developer identity and the local file is valid. The remote probes (AGH-134) run git against the
network, also the caller's: it passes ``remote_probes`` only from a Claude Code session, called
only when a rule reads the remotes. The workflows are the hub's and the built-ins, read as
``hub workflow`` reads them, when a rule reads them (AGH-227). The item folders (AGH-297) are
scanned by name only for temp-shaped entries an interrupted item write left beside a unit.
"""

import os
import stat
from collections.abc import Callable
from pathlib import Path

from agent_hub.core.doctor.finding import LISTING_READS, Read
from agent_hub.core.doctor.lock_rules import lock_paths, lock_state
from agent_hub.core.doctor.run_rules import Selection
from agent_hub.core.doctor.snapshot import (
    DoctorSnapshot,
    LockState,
    RemoteProbe,
    RepoFiles,
    hub_paths,
)
from agent_hub.core.hub_config.effective_identity import Sourced
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_files.hub_lock import HUB_LOCK_PATH
from agent_hub.core.hub_files.tree_snapshot import is_leftover_name
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS
from agent_hub.generator.built_json import base_hooks_block
from agent_hub.generator.doctor_tree import read_checkout, read_doctor_tree
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_tree import read_root_entry
from agent_hub.generator.workflow_discovery import HUB_WORKFLOWS
from agent_hub.generator.workflow_source import DiscoveredWorkflowSource

# The developer's effective branch prefix and its source, or None when no source gives one.
type BranchPrefixReader = Callable[[], Sourced | None]
# Each repo checkout's ``git ls-remote origin``, in ``hub.json`` order.
type RemoteProber = Callable[[], tuple[RemoteProbe, ...]]


def build_doctor_snapshot(
    root: str,
    *,
    config: HubConfig,
    running: str,
    selection: Selection,
    local: LocalConfig | tuple[ConfigProblem, ...],
    branch_prefix: BranchPrefixReader | None,
    remote_probes: RemoteProber | None = None,
) -> DoctorSnapshot:
    """The snapshot of the hub at ``root`` (its real path) for the selected rules."""
    reads = {read for rule in selection.rules for read in rule.reads}
    lock = read_lock(root) if Read.LOCK_PATHS in reads else None
    by_path = sorted({*hub_paths(config), *lock_paths(lock)})
    hub = read_doctor_tree(Path(root), by_path=by_path, listing=not LISTING_READS.isdisjoint(reads))
    base_hooks = base_hooks_block() if Read.BASE_HOOKS in reads else None
    repos = repo_checkouts(root, config) if Read.REPOS in reads else ()
    prefix = None
    if Read.DEVELOPER_IDENTITY in reads and isinstance(local, LocalConfig) and branch_prefix:
        prefix = branch_prefix()
    probes = remote_probes() if Read.REMOTES in reads and remote_probes else None
    workflows = DiscoveredWorkflowSource(Path(root)) if Read.WORKFLOWS in reads else None
    packs = pack_folders(root) if workflows is not None else ()
    leftovers, item_folders = item_leftovers(root) if Read.ITEM_FOLDERS in reads else (None, ())
    return DoctorSnapshot(
        config=config,
        running_version=running,
        hub=hub,
        lock=lock,
        base_hooks=base_hooks,
        repos=repos,
        local=local,
        branch_prefix=prefix,
        remote_probes=probes,
        workflows=workflows,
        workflow_folders=packs,
        item_leftovers=leftovers,
        item_folders=item_folders,
    )


# The folders a unit's temp entries sit in: ``.claude`` (its hook files), its skills and agents,
# and below ``plugin/<p>/`` its skills, agents and hooks; then each ``workflows/<pack>``.
_CLAUDE_FOLDERS = (".claude", ".claude/skills", ".claude/agents")
_PLUGIN_FOLDERS = ("skills", "agents", "hooks")


def item_leftovers(root: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The temp-shaped entries directly in the item folders, and the folders scanned, each in
    path order. A folder reached through a link is not scanned; at most the listing's names
    budget is examined in each."""
    plugins = tuple(f"plugin/{name}" for name in _sub_folders(root, "plugin"))
    candidates = [
        *_CLAUDE_FOLDERS,
        *(f"{plugin}/{folder}" for plugin in plugins for folder in _PLUGIN_FOLDERS),
        *(f"{HUB_WORKFLOWS}/{name}" for name in _sub_folders(root, HUB_WORKFLOWS)),
    ]
    scanned: list[str] = []
    found: list[str] = []
    for folder in sorted(candidates):
        names = _temp_names(root, folder)
        if names is not None:
            scanned.append(folder)
            found.extend(f"{folder}/{name}" for name in names)
    return tuple(sorted(found)), tuple(scanned)


def _plain_folder(root: str, folder: str) -> bool:
    """Whether every segment of ``folder`` is a folder, none of them a link."""
    path = root
    for segment in folder.split("/"):
        path = os.path.join(path, segment)
        try:
            if not stat.S_ISDIR(os.lstat(path).st_mode):
                return False
        except OSError:
            return False
    return True


def _sub_folders(root: str, folder: str) -> list[str]:
    if not _plain_folder(root, folder):
        return []
    try:
        with os.scandir(os.path.join(root, folder)) as listing:
            return sorted(e.name for e in listing if e.is_dir(follow_symlinks=False))
    except OSError:
        return []


def _temp_names(root: str, folder: str) -> list[str] | None:
    """The temp-shaped names in ``folder``, or None when it is no plain folder or cannot be
    listed."""
    if not _plain_folder(root, folder):
        return None
    names: list[str] = []
    try:
        with os.scandir(os.path.join(root, folder)) as listing:
            for examined, entry in enumerate(listing, start=1):
                if examined > DEFAULT_LIMITS.names_examined:
                    break
                if is_leftover_name(entry.name):
                    names.append(entry.name)
    except OSError:
        return None
    return sorted(names)


def pack_folders(root: str) -> tuple[str, ...]:
    """``workflows/<pack>`` for each folder directly under ``workflows/`` (links not followed)."""
    try:
        with os.scandir(os.path.join(root, HUB_WORKFLOWS)) as listing:
            names = sorted(e.name for e in listing if e.is_dir(follow_symlinks=False))
    except OSError:
        return ()
    return tuple(f"{HUB_WORKFLOWS}/{name}" for name in names)


def repo_checkouts(root: str, config: HubConfig) -> tuple[RepoFiles, ...]:
    """Each ``repos[].dir`` and the listed files of its checkout at ``../<dir>`` (spec D3, Q-9).

    ``../<dir>`` is taken as its real path once (plan E18), so a link to a folder is followed
    there only; absent or not a folder, the repo has no files. A checkout that cannot be listed
    carries the problem; one file that cannot be read does not (plan E36).
    """
    checkouts = (
        (repo.dir, os.path.realpath(os.path.join(root, os.pardir, repo.dir)))
        for repo in config.repos
    )
    return tuple(
        RepoFiles(dir=name, files=read_checkout(Path(real)) if _is_folder(real) else None)
        for name, real in checkouts
    )


def read_lock(root: str) -> LockState | None:
    """``hub.lock`` as found, never through a link; ``None`` when it cannot be read.

    An unreadable lock is not an absent one: ``hub.lock`` is a fixed path, so the tree read
    fails on it too and the run reports that problem instead of "not adopted".
    """
    try:
        return lock_state(read_root_entry(Path(root), HUB_LOCK_PATH))
    except GeneratorError:
        return None


def _is_folder(path: str) -> bool:
    """Whether ``path`` is a folder; one that cannot be looked at is left to the tree read."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except FileNotFoundError, NotADirectoryError:
        return False
    except OSError:
        return True
