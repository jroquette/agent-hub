"""Core's ``WorkflowSource`` over ``discover_workflows``: what ``hub workflow`` and hub web read.

Each file the discovery read is a ``WorkflowFile`` with its origin (hub or built-in), each
problem a ``LoadProblem`` keyed ``$``. A file is shown relative to the hub, a built-in's as
``<builtin>/<pack>/<file>``, so no absolute path of the installed package is shown.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from agent_hub.core.hub_config.problems import ROOT_PATH
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile
from agent_hub.generator.workflow_discovery import (
    BUILTIN_WORKFLOWS,
    WORKFLOW_SUFFIXES,
    discover_workflows,
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

    def workflow_files(self) -> Iterator[WorkflowFile | LoadProblem]:
        discovery = discover_workflows(self.root, builtin_root=self.builtin_root)
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
                shown = self._shown(found.path)
                yield WorkflowFile(shown, found.name, found.document, found.lines, found.origin)

    def _shown(self, path: Path) -> str:
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        if path.is_relative_to(self.builtin_root):
            return f"{BUILTIN_PREFIX}/{path.relative_to(self.builtin_root).as_posix()}"
        return str(path)
