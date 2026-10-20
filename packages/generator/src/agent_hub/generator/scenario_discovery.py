"""Find the scenarios a hub has: ``scenarios/<pack>/<name>.yaml`` (ADR 0041,
docs/design/scenarios.md § Contract).

The root is read as the hub's ``workflows/`` is (``workflow_discovery``: strict YAML, 256 KiB,
the name is the stem, no link, at most ``MAX_ROOT_WORKFLOWS`` files), with no built-ins, and it
takes only ``kind: scenario`` documents: any other is a problem, as a scenario is in
``workflows/``. An include resolves among the scenarios of its own pack.

``DiscoveredScenarioSource`` is core's ``WorkflowSource`` over it, so ``check_workflows`` loads
and plans each scenario and places each problem on its file, line and key.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile
from agent_hub.core.workflows.workflow_reads import SourceStat
from agent_hub.generator.workflow_discovery import (
    WorkflowDiscovery,
    WorkflowProblem,
    scan_root,
)
from agent_hub.generator.workflow_source import DiscoveredWorkflowSource, stats

HUB_SCENARIOS: Final = "scenarios"


def discover_scenarios(hub_root: Path) -> WorkflowDiscovery:
    """The hub's scenarios by name; a missing ``scenarios/`` reads as none."""
    problems: list[WorkflowProblem] = []
    root = scan_root(hub_root / HUB_SCENARIOS, kind="scenario", problems=problems)
    return WorkflowDiscovery(
        workflows=tuple(root.found[name] for name in sorted(root.found)),
        overridden=(),
        problems=tuple(problems),
    )


class DiscoveredScenarioSource(DiscoveredWorkflowSource):
    """The ``WorkflowSource`` of the scenarios of the hub at ``root``; ``only`` keeps one name's
    files. ``found`` holds each scenario the last ``workflow_files`` yielded (its pack)."""

    def __init__(self, root: Path, *, only: str | None = None) -> None:
        super().__init__(root, only=only)

    def workflow_files(self) -> Iterator[WorkflowFile | LoadProblem]:
        return self.files_of(discover_scenarios(self.root))

    def fingerprint(self) -> tuple[SourceStat, ...]:
        return tuple(stats(self.root / HUB_SCENARIOS, self._shown, depth=2))
