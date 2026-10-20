"""Core's ``WorkflowSource`` over ``discover_workflows``: what ``hub workflow`` and hub web read.

Each file the discovery read is a ``WorkflowFile`` with its origin (hub or built-in) and the
resolver of the workflows it may include (its own pack's), each
problem a ``LoadProblem`` keyed ``$``. A file is shown relative to the hub, a built-in's as
``<builtin>/<pack>/<file>``, so no absolute path of the installed package is shown.
``fingerprint`` lists the two roots stat-only (each entry's path as a file is shown, size and
mtime, two levels deep), so a reader can reuse what it planned while nothing changed and mark
each workflow file by its own entry.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final

from agent_hub.core.hub_config.problems import ROOT_PATH
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile
from agent_hub.core.workflows.workflow_reads import SourceStat
from agent_hub.generator.workflow_discovery import (
    BUILTIN_WORKFLOWS,
    HUB_WORKFLOWS,
    WORKFLOW_SUFFIXES,
    DiscoveredWorkflow,
    WorkflowDiscovery,
    discover_workflows,
    pack_resolver,
)

# How a built-in's file is shown: it lives in the installed package, not in the hub.
BUILTIN_PREFIX: Final = "<builtin>"


class DiscoveredWorkflowSource:
    """The ``WorkflowSource`` of the hub at ``root``; ``only`` keeps one name's files."""

    def __init__(
        self, root: Path, *, only: str | None = None, builtin_root: Path = BUILTIN_WORKFLOWS
    ) -> None:
        self.root = root
        self.only = only
        self.builtin_root = builtin_root
        # Each workflow the last ``workflow_files`` yielded, by name: its path and pack root.
        self.found: dict[str, DiscoveredWorkflow] = {}
        # The discovery the last ``workflow_files`` read: what its includes resolve against.
        self.discovery = WorkflowDiscovery(workflows=(), overridden=(), problems=())

    def workflow_files(self) -> Iterator[WorkflowFile | LoadProblem]:
        return self.files_of(discover_workflows(self.root, builtin_root=self.builtin_root))

    def files_of(self, discovery: WorkflowDiscovery) -> Iterator[WorkflowFile | LoadProblem]:
        """Each file ``discovery`` read, as ``workflow_files`` yields it."""
        self.discovery = discovery
        for problem in discovery.problems:
            # A folder's problem (a linked workflows/, an unreadable pack, the file budget)
            # bears on every name; a file's only on its own.
            on_folder = problem.path.suffix not in WORKFLOW_SUFFIXES
            if self.only is None or on_folder or problem.path.stem == self.only:
                yield LoadProblem(
                    self._shown(problem.path), problem.line, ROOT_PATH, problem.reason
                )
        for found in discovery.workflows:
            if self.only is None or found.name == self.only:
                self.found[found.name] = found
                shown = self._shown(found.path)
                # An include resolves among the workflows of its own pack.
                includes = pack_resolver(discovery, found.pack_root)
                yield WorkflowFile(
                    shown, found.name, found.document, found.lines, found.origin, includes
                )

    def fingerprint(self) -> tuple[SourceStat, ...]:
        """Each entry of the hub's ``workflows/`` and the built-ins, packs included, by the path
        ``WorkflowFile.file`` shows."""
        return (
            *stats(self.root / HUB_WORKFLOWS, self._shown, depth=2),
            *stats(self.builtin_root, self._shown, depth=2),
        )

    def _shown(self, path: Path) -> str:
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        if path.is_relative_to(self.builtin_root):
            return f"{BUILTIN_PREFIX}/{path.relative_to(self.builtin_root).as_posix()}"
        return str(path)


def stats(folder: Path, shown: Callable[[Path], str], *, depth: int) -> Iterator[SourceStat]:
    """Each entry under ``folder`` (``depth`` levels), stat-only, by its shown path."""
    try:
        with os.scandir(folder) as listing:
            entries = sorted(listing, key=lambda entry: entry.name)
    except OSError:
        return
    for entry in entries:
        try:
            stat = entry.stat()
        except OSError:
            yield (shown(Path(entry.path)), -1, -1)
            continue
        yield (shown(Path(entry.path)), stat.st_size, stat.st_mtime_ns)
        if depth > 1 and entry.is_dir(follow_symlinks=False):
            yield from stats(Path(entry.path), shown, depth=depth - 1)
