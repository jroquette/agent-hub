"""Synthetic doctor snapshots for the ``doctor`` unit tests: in memory, built from the builders."""

from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot, HubFiles
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry
from agent_hub.core.testing.builders import a_hub_document

RUNNING_VERSION = "0.2.0"

type SnapshotFactory = Callable[..., DoctorSnapshot]


@pytest.fixture
def snapshot_of() -> SnapshotFactory:
    """Build a ``DoctorSnapshot``: regular files by bytes, links by target, the builder's config.

    ``listed`` is the hub listing; ``None`` lists every file and link given, sorted.
    """

    def build(
        *,
        files: Mapping[str, bytes] | None = None,
        links: Mapping[str, str] | None = None,
        config: HubConfig | ConfigFailure | None = None,
        listed: tuple[str, ...] | None = None,
    ) -> DoctorSnapshot:
        entries: dict[str, TreeEntry] = {
            path: FileEntry(executable=False, content=content)
            for path, content in (files or {}).items()
        }
        entries |= {
            path: LinkEntry(target=target, outside=False) for path, target in (links or {}).items()
        }
        return DoctorSnapshot(
            config=HubConfig.model_validate(a_hub_document()) if config is None else config,
            running_version=RUNNING_VERSION,
            hub=HubFiles(
                entries=entries,
                listed=tuple(sorted(entries)) if listed is None else listed,
                problem=None,
            ),
        )

    return build
