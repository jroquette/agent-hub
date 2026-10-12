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
only when a rule reads the remotes.
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
from agent_hub.generator.built_json import base_hooks_block
from agent_hub.generator.doctor_tree import read_checkout, read_doctor_tree
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_tree import read_root_entry

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
    )


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
