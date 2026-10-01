"""Synthetic doctor snapshots for the ``doctor`` unit tests: in memory, built from the builders."""

from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.doctor.snapshot import (
    ConfigFailure,
    DoctorSnapshot,
    HubFiles,
    LockState,
    RepoFiles,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry
from agent_hub.core.json_form import JsonValue
from agent_hub.core.testing.builders import a_hub_document

RUNNING_VERSION = "0.2.0"

type SnapshotFactory = Callable[..., DoctorSnapshot]


@pytest.fixture
def snapshot_of() -> SnapshotFactory:
    """Build a ``DoctorSnapshot``: regular files by bytes, links by target, the builder's config.

    ``listed`` is the hub listing; ``None`` lists every file and link given, sorted. ``entries``
    adds entries of any kind (an executable file, a folder); ``lock`` is the lock read, ``None``
    when it was not; ``problem`` is why the hub's files could not all be listed or read, and
    ``paths_read`` whether every fixed and lock path was read (by default, when no ``problem``
    is given); ``base_hooks`` is
    the release's base hooks block, ``None`` when it was not built. ``repos`` maps each repo
    dir to its checkout's regular files by bytes, ``None`` when it has no checkout; keyed by repo
    dir, ``repo_links`` adds links by target, ``repo_listed`` replaces the checkout's listing
    (every file and link given, sorted, by default) and ``repo_problems`` says why it could not
    all be listed or read.
    """

    def build(
        *,
        files: Mapping[str, bytes] | None = None,
        links: Mapping[str, str] | None = None,
        config: HubConfig | ConfigFailure | None = None,
        listed: tuple[str, ...] | None = None,
        entries: Mapping[str, TreeEntry] | None = None,
        lock: LockState | None = None,
        problem: str | None = None,
        paths_read: bool | None = None,
        base_hooks: Mapping[str, JsonValue] | None = None,
        repos: Mapping[str, Mapping[str, bytes] | None] | None = None,
        repo_links: Mapping[str, Mapping[str, str]] | None = None,
        repo_listed: Mapping[str, tuple[str, ...]] | None = None,
        repo_problems: Mapping[str, str] | None = None,
    ) -> DoctorSnapshot:
        found: dict[str, TreeEntry] = {
            path: FileEntry(executable=False, content=content)
            for path, content in (files or {}).items()
        }
        found |= {
            path: LinkEntry(target=target, outside=False) for path, target in (links or {}).items()
        }
        found |= entries or {}
        return DoctorSnapshot(
            config=HubConfig.model_validate(a_hub_document()) if config is None else config,
            running_version=RUNNING_VERSION,
            hub=HubFiles(
                entries=found,
                listed=tuple(sorted(found)) if listed is None else listed,
                problem=problem,
                paths_read=problem is None if paths_read is None else paths_read,
            ),
            lock=lock,
            base_hooks=base_hooks,
            repos=tuple(
                RepoFiles(
                    dir=repo,
                    files=None
                    if files is None
                    else _checkout_of(
                        files,
                        links=(repo_links or {}).get(repo, {}),
                        listed=(repo_listed or {}).get(repo),
                        problem=(repo_problems or {}).get(repo),
                    ),
                )
                for repo, files in (repos or {}).items()
            ),
        )

    return build


def _checkout_of(
    files: Mapping[str, bytes],
    *,
    links: Mapping[str, str],
    listed: tuple[str, ...] | None,
    problem: str | None,
) -> HubFiles:
    """A checkout of regular files by bytes and links by target, listed as given or all."""
    found: dict[str, TreeEntry] = {
        path: FileEntry(executable=False, content=content) for path, content in files.items()
    }
    found |= {path: LinkEntry(target=target, outside=False) for path, target in links.items()}
    return HubFiles(
        entries=found,
        listed=tuple(sorted(found)) if listed is None else listed,
        problem=problem,
        paths_read=problem is None,
    )
